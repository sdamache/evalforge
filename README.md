# Incident-to-Insight Loop

> Transform LLM production failures into eval test cases, guardrail rules, and runbook entries — automatically.

[![AI Partner Catalyst Hackathon](https://img.shields.io/badge/Hackathon-AI%20Partner%20Catalyst-blue)](https://devpost.com)
[![Datadog](https://img.shields.io/badge/Powered%20by-Datadog-purple)](https://datadoghq.com)
[![Google Cloud](https://img.shields.io/badge/Built%20on-Google%20Cloud-4285F4)](https://cloud.google.com)

## 🎯 The Problem

**66% of organizations want AI that learns from feedback, but none have systematic pipelines to make it happen.**

When LLM agents fail in production:
- Incidents get investigated, then forgotten
- The same failures repeat weeks later
- Eval suites don't grow from real-world failures
- Runbooks don't exist for LLM-specific failure modes
- Teams fight the same fires over and over

## 💡 Our Solution

**Incident-to-Insight Loop** closes the feedback gap by automatically transforming every Datadog LLM trace failure into three actionable outputs:

1. **📝 Eval Test Cases** — Reproducible tests ready to add to CI/CD
2. **🛡️ Guardrail Rules** — Suggested rules to prevent recurrence
3. **📖 Runbook Entries** — Structured diagnosis and remediation steps

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Datadog                                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │ LLM Traces  │  │  Monitors   │  │  Custom Dashboard       │  │
│  │  (source)   │  │  (alerts)   │  │  (improvement backlog)  │  │
│  └──────┬──────┘  └──────┬──────┘  └─────────────▲───────────┘  │
└─────────┼────────────────┼───────────────────────┼──────────────┘
          │                │                       │
          ▼                ▼                       │
┌──────────────────────────────────────────────────┼─────────────┐
│                   Google Cloud                   │             │
│  ┌───────────────────────────────────────────────┴─────────┐   │
│  │                    Cloud Run                            │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │   │
│  │  │ Trace        │  │ Pattern      │  │ Suggestion    │  │   │
│  │  │ Ingestion    │──│ Extraction   │──│ Generator     │  │   │
│  │  │ Service      │  │ (Gemini)     │  │               │  │   │
│  │  └──────────────┘  └──────────────┘  └───────┬───────┘  │   │
│  └──────────────────────────────────────────────┼──────────┘   │
│                                                 │              │
│  ┌──────────────────────────────────────────────┼──────────┐   │
│  │                  Firestore                   │          │   │
│  │  ┌────────────┐  ┌────────────┐  ┌───────────▼──────┐   │   │
│  │  │ Failure    │  │ Improvement│  │ Approved         │   │   │
│  │  │ Patterns   │  │ Suggestions│  │ Improvements     │   │   │
│  │  └────────────┘  └────────────┘  └──────────────────┘   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                    Vertex AI                             │  │
│  │  • Gemini 2.5 Flash for pattern extraction               │  │
│  │  • Embeddings for similarity detection                   │  │
│  └──────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────┘
```

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Google Cloud SDK
- Datadog account with LLM Observability enabled
- Docker (for local development)

### Environment Setup

```bash
# Clone the repository
git clone https://github.com/sdamache/evalforge.git
cd evalforge

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -e ".[dev]"

# Copy environment template
cp .env.example .env
# Edit .env with your credentials
```

### Configuration

Create a `.env` file with:

```bash
# Datadog
DATADOG_API_KEY=your_api_key
DATADOG_APP_KEY=your_app_key
DATADOG_SITE=datadoghq.com

# Google Cloud
GOOGLE_CLOUD_PROJECT=your_project_id
GOOGLE_APPLICATION_CREDENTIALS=path/to/service-account.json

# Firestore
FIRESTORE_COLLECTION_PREFIX=i2i_

# Vertex AI
VERTEX_AI_LOCATION=us-central1
GEMINI_MODEL=gemini-2.5-flash
```

### Running Locally

```bash
# Start all services
docker-compose up

# Or run individual services
python -m src.ingestion.main
python -m src.api.main
```

### Creating Synthetic Datadog LLM Traces

We ship `scripts/generate_llm_trace_samples.py` so you can unblock development before live LLM traffic exists.

```bash
# Generate 5 sanitized traces and write them to tests/data/datadog_llm_trace_samples.json
python3 scripts/generate_llm_trace_samples.py --count 5

# Emit YAML instead of JSON so you can edit payloads in an IDE
python3 scripts/generate_llm_trace_samples.py --count 2 --format yaml --output /tmp/sample_traces.yaml

# Push the same traces into a Datadog trial org (requires ddtrace + API key)
DD_API_KEY=xxx python3 scripts/generate_llm_trace_samples.py --upload --count 3 --ml-app evalforge-demo
```

- Use `--site datadoghq.eu` or another site suffix to match your trial region.
- The pytest fixture reads `tests/data/datadog_llm_trace_samples.json` by default. Override the path with
  `DATADOG_TRACE_FIXTURE=/path/to/file.json pytest …` when you want to inspect different datasets.

## 📁 Project Structure

```
evalforge/
├── src/
│   ├── ingestion/          # Datadog trace ingestion service
│   ├── extraction/         # Gemini-powered pattern extraction
│   ├── generators/         # Eval, guardrail, runbook generators
│   ├── api/                # REST API for approval workflow
│   ├── dashboard/          # Datadog dashboard widgets
│   └── common/             # Shared utilities
├── tests/                  # Test suite
├── docs/                   # Documentation
├── scripts/                # Utility scripts
├── .github/
│   ├── workflows/          # CI/CD pipelines
│   └── ISSUE_TEMPLATE/     # Issue templates
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── README.md
```

## 🎬 Demo Scenario

**Before Incident-to-Insight Loop:**
1. E-commerce agent recommends discontinued product
2. Customer complains, support escalates
3. Engineer investigates Datadog trace, writes incident report
4. Three weeks later: same failure, different product
5. No one remembers the first incident

**After Incident-to-Insight Loop:**
1. Same failure occurs
2. Within minutes, engineer sees in dashboard:
   - ✅ Auto-generated eval case ready to add to CI/CD
   - ✅ Suggested guardrail: "Block recommendations for stale products"
   - ✅ Runbook draft: "Inventory staleness failures - diagnosis steps"
3. One-click approve → Next deployment includes the fix
4. **Feedback loop closed. System gets stronger.**

## 🛠️ Tech Stack

| Component | Technology |
|-----------|------------|
| Runtime   | Python 3.11 |
| API Framework | FastAPI |
| Cloud Platform | Google Cloud Run |
| AI/ML | Vertex AI (Gemini 2.5 Flash) |
| Database | Firestore |
| Observability | Datadog LLM Observability |
| CI/CD | GitHub Actions |

## 📊 Milestones

- [x] Week 1: Foundation (Trace ingestion, Pattern extraction, Storage)
- [ ] Week 2: Core Generators (Eval, Guardrail, Runbook)
- [ ] Week 3: Integration (Dashboard, Approval API)
- [ ] Week 4: Demo and Polish

## 🤝 Contributing

This is a hackathon project! Feel free to open issues or PRs.

## 📜 License

MIT License - see [LICENSE](LICENSE) for details.

## 🙏 Acknowledgments

- **AI Partner Catalyst: Accelerate Innovation Hackathon**
- **Datadog** for LLM Observability
- **Google Cloud** for Vertex AI and Cloud Run

---

Built with ❤️ for the AI Partner Catalyst Hackathon
