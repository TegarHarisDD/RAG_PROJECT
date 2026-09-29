PRD: RAG Portfolio Demo
=======================

**Status:** Draft v1 | **Type:** Portfolio project | **Owner:** You

1\. Overview
------------

A public web app where visitors ask questions about a fixed set of documents and get streamed answers with citations. The goal is to show end-to-end RAG skills (ingestion, retrieval, generation, evaluation, deployment) in a small, reliable, live demo.

2\. Goals and Non-Goals
-----------------------

**Goals**

*   Live demo that answers questions accurately from one document set
    
*   Streaming chat UI with visible source citations
    
*   Clean, documented codebase that a recruiter or engineer can read in 10 minutes
    
*   Near-zero running cost
    

**Non-Goals**

*   User accounts, login, or per-user data
    
*   User document uploads (fixed corpus only)
    
*   Multi-tenant, enterprise scale, or high availability
    
*   Fine-tuning or training models
    

3\. Target Users
----------------

**UserNeed**Recruiter / hiring managerQuickly see a working, polished AI projectEngineer reviewing the repoUnderstand design choices and code qualityCasual visitorAsk a question and get a trustworthy answer

4\. User Stories
----------------

1.  As a visitor, I can type a question and see the answer stream in.
    
2.  As a visitor, I can see which document, page, and snippet each answer came from.
    
3.  As a visitor, I can click an example question to try the demo instantly.
    
4.  As a visitor, I get a clear "I couldn't find that in the documents" when the answer isn't there.
    
5.  As a reviewer, I can read the README to understand architecture, decisions, and evaluation results.
    

5\. Functional Requirements
---------------------------

**Must have (MVP)**

*   **FR1 Ingestion script:** parse PDFs/text, chunk (300-800 tokens, small overlap), embed, store in MongoDB with metadata (source, page, chunk id, embedding model, dimension).
    
*   **FR2 Retrieval:** vector search over top-k chunks (k = 4-5).
    
*   **FR3 Generation:** send question and retrieved chunks to an LLM via OpenRouter with a strict prompt: answer only from context, cite sources, say so if unknown.
    
*   **FR4 Streaming API:** POST /ask returns tokens via Server-Sent Events, followed by a citations payload.
    
*   **FR5 Chat UI:** React interface with message history (in session only), streaming text, and expandable citation cards.
    
*   **FR6 Example questions:** 3-5 clickable starter prompts.
    
*   **FR7 Abuse protection:** per-IP rate limit and max question length.
    
*   **FR8 Health endpoint:** GET /health for hosting checks.
    

**Should have**

*   Loading and error states (including "server waking up" for sleeping free-tier hosts)
    
*   Evaluation script and results table in the README
    
*   Dark mode
    

**Could have (stretch)**

*   Hybrid search (vector + keyword via Atlas Search)
    
*   Reranker
    
*   Feedback thumbs up/down stored in MongoDB
    
*   Model selector between two OpenRouter models
    

6\. Non-Functional Requirements
-------------------------------

**AreaTarget**Time to first tokenUnder 3 seconds (excluding cold start)Cold startCommunicated in UI; under 60 secondsCostUnder a few dollars per month; hard usage capsSecurityAPI keys only on backend; no secrets in the repo or frontendPrivacyCorpus must be public documents (embeddings and chunks go to third-party APIs)ReliabilityGraceful errors if OpenRouter or MongoDB fails

7\. Technical Approach
----------------------

**LayerChoice**FrontendReact (Vite) + Tailwind, hosted on Vercel or NetlifyBackendFastAPI, hosted on Render or RailwayDatabaseMongoDB Atlas free tier (M0) with Atlas Vector SearchEmbeddingsOpenRouter embedding model (free or low-cost)LLMOpenRouter (cheap or free model; small credit balance recommended for higher limits)Parsingpypdf or pymupdf

**Architecture flow:** React → FastAPI /ask → embed question → Atlas vector search → build prompt → OpenRouter LLM → stream tokens and citations back to React.

**Key design decisions**

*   Wrap embed() and generate() in thin functions so providers can be swapped.
    
*   Store embedding model name and dimension with every vector; changing models requires re-indexing.
    
*   No Celery, Redis, or auth; ingestion is a one-off script.
    

Data model (collection chunks) { \_id, text, embedding\[\], source, page, chunk\_index, embedding\_model, dim }

8\. Demo Dataset
----------------

**To be decided.** Requirements: publicly available, 20-100 pages, focused topic, text-based PDFs, a license that allows reuse. The dataset must be stated clearly on the landing page.

9\. Success Metrics
-------------------

**MetricTarget**Eval set accuracy20-50 questions; at least 80% answered correctly with correct citation"Not in documents" handlingAt least 90% correct refusals on out-of-scope questionsLive demo uptimeLoads and answers on first try when reviewedREADME qualityIncludes architecture diagram, design decisions, limitations, eval resultsMonthly costWithin budget cap

10\. Risks and Mitigations
--------------------------

**RiskMitigation**Free-tier hosting sleeps, slow first loadLoading message; optional uptime pingerFree OpenRouter models rate limited or removedSmall credit balance; model name in config, not hardcodedFree embedding routes return 404 if privacy settings block training providersAdjust OpenRouter privacy setting, or use a paid embedding modelStrangers drain creditsRate limiting, length caps, spending limit on OpenRouterHallucinated answersStrict prompt, low temperature, citations, eval setAtlas M0 storage (512 MB) fills upKeep corpus small; use smaller embedding dimensions if needed

11\. Milestones
---------------

**#MilestoneDeliverable**1Data and indexAtlas cluster, vector index, ingest.py working2Retrieval and generationrag.py tested from CLI3API/ask streaming endpoint and rate limiting4UIReact chat with citations and examples5EvaluationQuestion set and results table6Deploy and documentLive URLs, README with diagram7StretchHybrid search, reranker, feedback

12\. Open Questions
-------------------

1.  Which document set will the demo use?
    
2.  FastAPI confirmed as the backend (instead of Django)?
    
3.  Which OpenRouter embedding and LLM models, free or paid?
    
4.  Monthly budget cap for API usage?
    
5.  Custom domain, or default hosting URLs?