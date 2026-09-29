# Corpus

The demo's single fixed Corpus (spec: EU AI Act).

`eu-ai-act.pdf` — Regulation (EU) 2024/1689 (Artificial Intelligence Act),
authentic Official Journal English PDF, CELEX 32024R1689. Public EU document;
reuse permitted under the EU's reuse policy. Fetched from the Publications
Office cellar service (`http://publications.europa.eu/resource/celex/32024R1689`,
content negotiation `Accept: application/pdf`) because EUR-Lex's direct PDF
endpoint sits behind an AWS WAF challenge.

The ingest script (`backend/app/ingest.py`) parses this file, strips the
annexes, chunks it, and stores the Chunks in Atlas.
