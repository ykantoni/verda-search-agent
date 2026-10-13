# verda-search-agent

A self-hosted AI agent for the [`verda-cloud`](https://github.com/ykantoni/verda-cloud)
lab cluster: answers questions grounded in local PDF/DOC/DOCX/TXT files,
using a [LangGraph](https://github.com/langchain-ai/langgraph) agent that
calls a local [MCP](https://modelcontextprotocol.io/) search server, with
the cluster's own self-hosted [vLLM](https://docs.vllm.ai/) deployment
(`verda-k8s-apps`'s `vllm` app) as its LLM backend — no external LLM API,
no external search service.

Deployed to the cluster via `verda-k8s-apps/argocd-apps/search-agent.yaml`
(see that repo). This repo only holds the application source and its
container builds — it never runs `terraform`/`kubectl` itself, same
separation of concerns as every other app in this project.

## Structure

- [`specs/`](specs) — the design inputs this was built from:
  [`SKILL.md`](specs/SKILL.md) (the agent's answer-grounding workflow and
  rules) and [`local-search-mcp-server.json`](specs/local-search-mcp-server.json)
  (the exact MCP tool contract the server implements).
- [`mcp-server/`](mcp-server) — the `local-docs` MCP server: indexes
  `/data/docs` (PDF via `pypdf`, DOCX via `python-docx`, TXT directly,
  legacy `.doc` best-effort via `antiword`) into an in-memory BM25
  keyword index at startup, and exposes exactly the two tools from
  `specs/local-search-mcp-server.json` (`search_documents`,
  `get_document_chunk`) over streamable-HTTP MCP on port `8001`. No
  semantic/embedding search in v1 — BM25 keeps this dependency-light and
  needs no model to run; revisit only if relevance proves insufficient.
- [`agent/`](agent) — the LangGraph agent. A FastAPI service
  (`POST /ask {"question": "..."}` → `{"answer": ..., "sources": [...]}`,
  port `8000`) wrapping a `create_react_agent` graph whose system prompt
  encodes `specs/SKILL.md`'s workflow (search → fetch → answer only from
  retrieved text → cite sources → say so explicitly if nothing is found),
  with the two MCP tools bound via `langchain-mcp-adapters`, and an
  OpenAI-compatible `ChatOpenAI` client pointed at the in-cluster vLLM
  router.

## Deployment shape

Agent and MCP server run as two containers in **one Pod** (sidecar
pattern) — they share a network namespace, so the agent reaches the MCP
server at `http://localhost:8001/mcp` with no extra Service or auth layer
needed for that hop. Only the agent's own port is exposed outside the
Pod. See `verda-k8s-apps/search-agent/` for the actual manifests
(`Deployment`, `Service` on NodePort `30096`, a Longhorn-backed PVC for
`/data/docs`).

## Populating the document store

There's no automated ingestion pipeline in v1 — after the `search-agent`
Application is `Synced`/`Healthy`, copy files directly into the running
pod's PVC mount:

```bash
kubectl -n search-agent cp ./some-report.pdf $(kubectl -n search-agent get pod -l app=search-agent -o jsonpath='{.items[0].metadata.name}'):/data/docs/ -c mcp-server
```

Then restart the pod (`kubectl -n search-agent rollout restart deployment/search-agent`)
to force a re-scan — the index is built once at startup, not watched for
changes.

## Building images

CI (`.github/workflows/build.yaml`) builds and pushes both images to GHCR
on every push to `main`:

- `ghcr.io/ykantoni/verda-search-agent-agent:latest`
- `ghcr.io/ykantoni/verda-search-agent-mcp:latest`

To build locally instead:

```bash
docker build -t verda-search-agent-agent agent/
docker build -t verda-search-agent-mcp mcp-server/
```

If the GHCR packages are private rather than public, the `search-agent`
Deployment in `verda-k8s-apps` will need an `imagePullSecret` added —
not set up yet.

## Testing the endpoint

```bash
curl http://<any-node-ip>:30096/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the database high-availability architecture?"}'
```
