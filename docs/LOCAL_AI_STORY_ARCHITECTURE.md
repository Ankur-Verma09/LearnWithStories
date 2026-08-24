# Local AI Story Generation Architecture

## A. Current architecture

The existing application is an offline-first Python/SQLite service with a dependency-free browser UI.

```text
Browser UI
  -> POST /api/lesson
  -> StoryTutorAgent
     -> ContextMemoryManager
     -> Retriever -> approved SQLite source_chunks
     -> StoryPromptBuilder
     -> LLMProvider -> OllamaProvider or OpenAIProvider
     -> deterministic schema validation
     -> evidence-based LLM verification and one repair attempt
     -> verified lesson cache and learning history
  -> story, structured explanation, recall quiz, and sources
```

Document upload already supports PDF, DOCX, TXT, and JSONL conversion. The approved-source hierarchy and lexical retriever form the current RAG layer. The provider layer uses the same business workflow for Ollama and OpenAI. Examinations reuse the model and evidence layers but retain their own deterministic domain service.

## B. Gap analysis

| Requirement | Existing capability | Gap addressed |
|---|---|---|
| Local model | Ollama client and health check | Gemma 3 configuration and keep-alive defaults |
| Provider portability | Shared model client and provider factory | Explicit `LLMProvider` contract and registry |
| RAG grounding | Approved chunks and bounded retrieval | Prompt boundary now labels evidence as untrusted data |
| Adaptive learning | One numeric understanding level | Separate learner age and knowledge level |
| Learning profiles | Hard-coded numeric guides | Configurable contiguous age bands and independent knowledge profiles |
| Prompt construction | System prompts centralized; payload assembled in agent | Dedicated `StoryPromptBuilder` |
| Structured response | Story, facts, memory hook, and three MCQs | Added summary, key points, real-world example, fun fact, and server-owned metadata |
| Validation | Evidence markers, question count/options, verifier/repair | Dedicated deterministic schema checks, including distinct answers |
| Caching | Evidence/context/model-aware SHA-256 cache | Age, age profile, knowledge, style, difficulty, and provider included |
| Observability | Lesson event | Safe per-stage model metrics and request correlation without prompt logging |
| Failure handling | Public-safe model errors and repair | Bounded transport retries and richer local-provider settings |
| Testing | API, hierarchy, exam, UI, and key-pool suites | Adaptive profiles, prompts, schema, migration, cache, mocked pipeline, and quality fixture |

## C. Proposed architecture and decisions

### Added

- Configurable `LearningProfileEngine`.
- Independent `age` and `knowledge_level` request dimensions.
- `StoryPromptBuilder` and deterministic lesson schema module.
- Provider registry and safe generation telemetry.
- Golden quality-evaluation cases.

### Modified

- Agent orchestration, cache material, provider settings, lesson persistence, API contract, CLI, Learn form, and lesson rendering.
- Default local example uses `gemma3:12b` through Ollama.

### Reused

- Approved document pipeline, retriever, learner memory, factual verification/repair, SQLite, lesson cache, quiz scoring, web server, Docker, and Cloudflare routing.

### Removed

- No existing subsystem was removed. The legacy `level` API field and `understanding_level` database column remain as backward-compatible age aliases.

## Age and knowledge-level rule

Age controls vocabulary, sentence style, relatable situations, analogy frequency, and appropriate humor. Knowledge level controls prerequisites, terminology, reasoning complexity, and technical depth.

Therefore:

- A 28-year-old beginner receives adult situations and vocabulary with foundational technical depth.
- A 16-year-old advanced learner receives teenage situations and age-appropriate language with advanced evidence-bounded technical depth.

The model is explicitly instructed never to infer knowledge from age.

## D. File-level change plan

| File/module | Change | Dependency | Risk/control |
|---|---|---|---|
| `config/learning_profiles.json` | Age bands and knowledge profiles | None | Configuration validation fails closed |
| `learning_profiles.py` | Resolve and validate adaptive profile | Profile JSON | Age and knowledge tested independently |
| `prompt_builder.py` | Central structured prompt payloads | Profile data | No private full-prompt logging |
| `schemas.py` | Validate rich output and add server metadata | Evidence IDs | Invalid lessons repaired or withheld |
| `model_client.py` | Provider registry, keep-alive, retries, metrics | Settings | Bounded retries only |
| `agent.py` | Orchestrate adaptive grounded pipeline | Existing RAG/memory/DB | Existing positional API preserved |
| `db.py` | Add adaptive and telemetry columns | SQLite | Additive migration; old rows retained |
| `web_server.py` | API v5 adaptive fields | Agent/settings | Legacy `level` accepted |
| `web/index.html`, `web/app.js` | Separate age and knowledge controls | API v5 | Existing navigation/forms unchanged |
| `tests/` | Unit, migration, pipeline, UI/API contracts | Standard library | Real Ollama tests remain environment-gated |

## E. Implementation phases

| Phase | Status |
|---|---|
| 1. Local Ollama integration | Reused and configured for Gemma 3 |
| 2. LLM provider abstraction | Completed |
| 3. Learning-level engine | Completed with separate age/knowledge dimensions |
| 4. Structured story generation | Completed |
| 5. Response validation | Completed |
| 6. Quiz generation | Reused and strengthened |
| 7. Caching and observability | Completed |
| 8. RAG integration | Existing lexical approved-source RAG reused; embeddings/vector store remain future work |
| 9. Automated/model-quality tests | Deterministic suite and golden dataset added; live Gemma evaluation requires RTX runtime |

## Security and operational boundaries

- Questions, learner context, and retrieved documents are explicitly treated as untrusted data rather than model instructions.
- Model output cannot set authoritative subject, topic, age, knowledge level, style, or difficulty metadata.
- Ollama must remain on the private LAN and must not be exposed through router port forwarding or a public tunnel.
- No complete prompt, API key, or private learner content is written to generation telemetry.
- Only lessons that pass deterministic structure checks and factual verification are published.
