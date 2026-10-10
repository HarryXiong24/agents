# Deep research agent

Run from the repository root:

```bash
uv run python -m agent_apps.deep_research_agent
```

Configuration is loaded from the repository root `.env`, independently of the
working directory. Values in that file override existing environment variables.
Restart the application after changing them.

| `PROVIDER` | Model | API key | Optional base URL |
| --- | --- | --- | --- |
| `ollama` | `OLLAMA_MODEL` | `OLLAMA_API_KEY` (optional for local Ollama) | `OLLAMA_BASE_URL` |
| `openrouter` | `OPEN_ROUTER_MODEL` | `OPEN_ROUTER_API_KEY` | `OPEN_ROUTER_BASE_URL` |
| `openai` | `OPENAI_MODEL` | `OPENAI_API_KEY` | `OPENAI_BASE_URL` |

All four agents use the selected provider and model. OpenAI uses the Responses
API; Ollama and OpenRouter use the Chat Completions API.

The existing `WebSearchTool` requires the OpenAI Responses API, so the complete
research workflow currently requires `PROVIDER=openai`. Using Ollama/OpenRouter
for the complete workflow requires replacing that tool with a compatible search
function. The workflow checks this before making model requests.

Additional settings in the same `.env`:

- `HOW_MANY_SEARCHES`: positive integer, default `5`.
- `USE_EMAIL`: default `true`; set `false` to send via Pushover instead.
- Email delivery: `EMAIL_ADDRESS`, `EMAIL_SMTP_SERVER`, `EMAIL_APP_PASSWORD`.
- Pushover delivery: `PUSHOVER_USER`, `PUSHOVER_TOKEN`.

Configure the chosen delivery service before running the complete workflow.
The report is displayed before notification delivery. If notification delivery
raises an error, the report stays visible with a failure message.
