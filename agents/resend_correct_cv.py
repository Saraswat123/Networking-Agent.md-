"""Re-send all today's emails with the correct CV (cv_main_generic.pdf).
Does NOT modify queue — companies already logged. Just corrects the attachment."""
import os, smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path("/Users/aitsgroup/networking-agent/.env"))
GMAIL  = os.environ["GMAIL_ADDRESS"]
APP_PW = os.environ["GMAIL_APP_PASSWORD"].replace(" ", "")

CV = Path("/Users/aitsgroup/networking-agent/agents/output/pdfs/cv_main_generic.pdf")

SIGN = "\n\nWarm regards and looking forward to connecting,\n\nSaraswat Das\nsaraswatdas94@gmail.com | saraswat.vercel.app | github.com/Saraswat123"

TARGETS = [
    # --- Healthcare batch 1 ---
    {
        "company": "Pharos",
        "to": ["felix@pharos.health"],
        "subject": "Eliminated 80% manual data ops across 50+ staff via AI extraction — relevant for Pharos",
        "body": """Hey Felix,

Hospitals lose thousands of clinician-hours to manual chart review not because the data doesn't exist in the EHR — but because it's unstructured, inconsistent across records, and no one has built the extraction layer that makes it queryable at scale. That's the gap Pharos closes, and it's the exact class of problem I've already shipped in production.

At AITS Group, I built an AI document extraction pipeline (Claude Vision API) that pulled 11 structured parameters per document with per-field confidence scoring — replacing manual review for 50+ staff across 15 locations. On top: a multi-agent orchestration layer (Classifier → Detector → Generator, 9 concurrent API calls) that flagged anomalies and auto-generated reports. Underneath: 15 API integrations unified into a 30-table PostgreSQL warehouse with 40+ live KPIs giving leadership daily visibility. Result: 85% org efficiency gain, 80% reduction in manual data ops. Zero manual report generation.

The architecture maps directly to hospital quality: unstructured clinical notes → structured extraction with confidence scoring → anomaly flagging → automated reporting to quality teams. Same pipeline, different documents.

Fully remote, $30–50K USD annually.

Happy to jump on a 15-min call.""" + SIGN,
    },
    {
        "company": "Phases",
        "to": ["founders@phases.ai"],
        "subject": "Built multi-agent AI + compliance data pipeline for regulated ops — Phases",
        "body": """Hey James, Anton, and Jonathan,

Clinical trial recruitment fails at the data layer: patient records arrive in unstructured formats, eligibility screening requires consistent field extraction across documents, and every decision needs an audit trail for regulatory review. The teams that solve it build a pipeline — not just an AI that summarizes.

I've shipped this class of system in production. At AITS Group, I built a multi-agent orchestration layer — 9 concurrent Claude API calls (Classifier → Detector → Generator agents) with a Rust MCP server (11 live tool endpoints, JSON-RPC 2.0, zero GC pauses) that handled: structured audit logs per call, PII redaction middleware on all inputs, per-tool rate limiting, and schema-validated outputs. Document extraction: Claude Vision pipeline pulling 11 structured parameters per document with confidence scoring. Underneath: 15 API integrations into a 30-table PostgreSQL warehouse. Result: 90% reduction in manual ops overhead, 95% data accuracy, 85% org efficiency gain across 50+ staff.

Having built AI data pipelines at J&J and Syneos, you know the compliance layer is where most systems break. I'd like to work on the infrastructure that makes Polly reliable at scale.

Fully remote, $30–50K USD annually.

Happy to jump on a 15-min call.""" + SIGN,
    },
    {
        "company": "Care GP",
        "to": ["melvin@caregp.com.au"],
        "subject": "Eliminated 90% admin overhead for 100+ healthcare workers via AI — Care GP",
        "body": """Hey Melvin,

Primary care admin breaks the same way every time: GPs and staff spend hours on scheduling, documentation, and coordination that has nothing to do with patient care. The practices that get AI right don't just add a chatbot — they rebuild the ops layer so the administrative work happens automatically, in the background, without anyone thinking about it.

I've built exactly this. At AITS Group, I deployed an AI automation stack that eliminated 90% of repetitive operational work for 50+ staff across 15 locations — automated scheduling workflows, document processing (Claude Vision, 11 structured parameters per document), LLM-generated call scripts and communications, and a 30-KPI live dashboard giving leadership daily visibility. Managing 100+ team members through automated HRMS workflows with 90% improvement in work distribution. 85% org efficiency gain, 75% work efficiency improvement — all measured.

For primary care: appointment scheduling, referral tracking, patient communication, and clinical documentation can all run through the same automation layer. I'd like to build that for Care GP.

Fully remote, $30–50K USD annually.

Happy to jump on a 15-min call.""" + SIGN,
    },
    {
        "company": "Opencall",
        "to": ["ask@opencall.ai"],
        "subject": "Built 15 API integrations + LLM automation layer for 50-staff ops — Opencall",
        "body": """Hey Oliver, Eric, and Arthur,

An AI receptionist is only as good as the backend it's connected to. If the EHR integration lags, appointment slots in the AI's context are stale. If the scheduling API returns inconsistent formats, the booking logic breaks. If there's no structured audit trail, you can't debug why a patient got the wrong slot. The product your customers see is great — the infrastructure underneath determines whether it holds up at scale.

I've built this integration layer in production. At AITS Group, I architected 15 REST API integrations (CRM, HRMS, payment processors, scheduling systems, EdTech APIs) unified into a 30-table PostgreSQL warehouse — live sync, webhook handling with error recovery, schema normalization across inconsistent source formats. On top: a multi-model LLM stack (Claude, Ollama, Grok, MCP) generating personalized communications and automating workflows. 40+ live KPIs with 95% data accuracy. Result: 90% reduction in manual ops for 50+ staff, 80% employee productivity improvement.

For Opencall: reliable EHR sync, consistent slot availability data, structured call outcome logging, and automated follow-up workflows — that's the backend reliability layer that makes your AI receptionist trustworthy at scale.

Fully remote, $30–50K USD annually.

Happy to jump on a 15-min call.""" + SIGN,
    },
    # --- Fintech batch 1 ---
    {
        "company": "Accend",
        "to": ["info@withaccend.com"],
        "subject": "Cut financial document processing time 80% via AI extraction — relevant for Accend",
        "body": """Hey Pranjal, Yutong, and Joseph,

An underwriting AI that accelerates decisions by 80% is impressive — but that number depends entirely on the quality of structured data flowing into it. If the financial statement extraction missed a line item, or the cash flow model was built on a document where the LLM hallucinated a field value, the speed gain creates a liability instead of a win. The extraction layer is where underwriting AI either earns trust or loses it.

I've built document extraction pipelines with this class of reliability in production. At AITS Group, I shipped a Claude Vision extraction system pulling 11 structured parameters per document with per-field confidence scoring — feeding a multi-agent orchestration layer (Classifier → Detector → Generator, 9 concurrent API calls) that flagged anomalies before they propagated downstream. Compliance infrastructure: PII redaction middleware, per-call structured audit logs, rate limiting, schema-validated outputs. Underneath: 15 API integrations unified into a 30-table PostgreSQL warehouse. Result: 85% org efficiency gain, 90% reduction in manual ops, 95% data accuracy across 50+ staff.

For commercial underwriting: structured extraction from financial statements with confidence scoring, anomaly detection on cash flow patterns, automated credit memo generation with full audit trail — the infrastructure that makes the AI decision defensible to compliance and regulators.

Fully remote, $30–50K USD annually.

Happy to jump on a 15-min call.""" + SIGN,
    },
    {
        "company": "Harmoney",
        "to": ["sales@harmoney.in"],
        "subject": "Built multi-agent AI data pipeline for financial analytics ops — Harmoney",
        "body": """Hey Aditya, Amal, and Omkar,

Fixed income analysis at scale has a data pipeline problem before it has an AI problem. Market data arrives from multiple sources with inconsistent schemas, credit rating feeds update asynchronously, financial statement data lives in unstructured documents, and a portfolio manager needs all of it normalized, reconciled, and queryable in real time before the AI can do anything useful with it. That layer is usually the last thing teams build — and the first thing that breaks.

I've built exactly this layer in production. At AITS Group, I architected 15 REST API integrations unified into a 30-table PostgreSQL warehouse — live sync with webhook handling, schema normalization across inconsistent source formats, and error recovery. On top: a multi-agent AI orchestration system (9 concurrent Claude API calls, specialized agents for classification, anomaly detection, and generation) with a 30-KPI live dashboard delivering 95% data accuracy and daily leadership visibility. 85% org efficiency gain, 90% reduction in manual data ops.

For fixed income AI: multi-source data ingestion (market feeds, ratings, filings) → normalized warehouse → AI agents for analysis and portfolio optimization → live dashboards for portfolio managers. Same architecture, different data domain.

Fully remote, $30–50K USD annually.

Happy to jump on a 15-min call.""" + SIGN,
    },
    {
        "company": "Jenfi",
        "to": ["hello@jenfi.com"],
        "subject": "Built automated revenue data pipeline + real-time KPIs for multi-location ops — Jenfi",
        "body": """Hey Jenfi team,

Revenue-based financing decisions are only as fast as the data pipeline feeding them. If your underwriting system is pulling revenue data manually from Stripe, Shopify, and Google Ads for each applicant — or if the monitoring layer that tracks repayment capacity post-disbursement requires manual reconciliation — you're leaving both speed and risk control on the table. The companies that get RBF right automate the data layer end to end.

I've built this class of integration layer in production. At AITS Group, I architected 15 REST API integrations unified into a 30-table PostgreSQL warehouse — live sync across 15 locations, webhook handling with error recovery, schema normalization, and automated anomaly alerts. On top: a multi-model LLM layer for automated reporting and decision support, and a 40+ KPI live dashboard with 95% data accuracy. Result: 90% reduction in manual data ops, 85% org efficiency gain across 50+ staff.

For Jenfi: automated revenue data ingestion from digital platforms (Shopify, Stripe, Meta Ads, Google Analytics) → normalized real-time warehouse → automated eligibility scoring → live portfolio monitoring with anomaly alerts. Faster underwriting, fewer bad calls.

Fully remote, $30–50K USD annually.

Happy to jump on a 15-min call.""" + SIGN,
    },
    # --- Stardex ---
    {
        "company": "Stardex",
        "to": ["sanket@stardex.ai"],
        "subject": "Built LLM automation + 15 API integrations for 100+ workforce ops — Stardex",
        "body": """Hey Sanket,

Executive search firms lose placements not because they lack good recruiters — but because their candidate pipeline data goes stale, follow-up timing slips, and the CRM reflects what was true three weeks ago, not today. The firms that win are the ones with real-time visibility into every open role, every candidate conversation, and every client relationship. That's a data + automation problem, and the ATS that solves it owns the workflow.

I've built this class of system in production. At AITS Group, I deployed an automation layer that manages 100+ workforce members across 15 locations from a single Founders Office — automated HRMS workflows, LLM-generated call scripts and follow-up emails (Claude + Ollama), real-time activity tracking, escalation flows, and manager dashboards. Underneath: 15 API integrations unified into a 30-table PostgreSQL warehouse with 40+ live KPIs and 95% data accuracy. Result: 90% work distribution improvement, 80% employee productivity gain, zero manual reporting.

For Stardex: automated candidate status tracking, LLM-drafted outreach sequences, real-time pipeline dashboards for search consultants, and integration with LinkedIn/job boards → the same architecture that made a 15-location EdTech operation run without manual intervention.

Fully remote, $30–50K USD annually.

Happy to jump on a 15-min call.""" + SIGN,
    },
    # --- Structured AI ---
    {
        "company": "Structured AI",
        "to": ["info@getstructured.ai"],
        "subject": "Built AI document extraction pipeline with confidence scoring — relevant for Structured AI",
        "body": """Hey Raymond, Issy, and Brandon,

Construction change orders cost 15–20% of contract value on average — and most trace back to design errors that existed in the drawings weeks before anyone caught them. The value Structured AI creates is directly proportional to how precisely your AI catches real errors vs. noise. A system that flags 40 issues per drawing and is right on 20 of them doesn't get used. One that flags 12 and is right on 11 becomes the standard in every review workflow.

That precision problem starts at the extraction layer. I've built this in production. At AITS Group, I shipped a Claude Vision extraction pipeline pulling 11 structured parameters per document with per-field confidence scoring — feeding a multi-agent orchestration layer (Classifier → Detector → Generator, 9 concurrent API calls) that only escalated anomalies where confidence dropped below threshold. Result: high-signal output engineers could act on, not a list of false positives to manually triage. Underneath: 15 API integrations into a 30-table PostgreSQL warehouse, 40+ live KPIs, 95% data accuracy. 85% org efficiency gain, 80% reduction in manual review overhead across 50+ staff.

For Structured AI: the same confidence-scored extraction architecture applied to engineering symbols and drawing parameters — flagging only the inconsistencies worth an engineer's attention, with an audit trail per check for accountability. Every error caught in design is a change order that never gets written.

Fully remote, $30–50K USD annually.

Happy to jump on a 15-min call.""" + SIGN,
    },
]

def send(t):
    msg = MIMEMultipart("mixed")
    msg["From"] = f"Saraswat Das <{GMAIL}>"
    msg["To"]   = ", ".join(t["to"])
    msg["Subject"] = t["subject"]
    msg.attach(MIMEText(t["body"], "plain"))
    with open(CV, "rb") as f:
        p = MIMEApplication(f.read(), Name=CV.name)
    p["Content-Disposition"] = f'attachment; filename="{CV.name}"'
    msg.attach(p)
    with smtplib.SMTP("smtp.gmail.com", 587) as s:
        s.ehlo(); s.starttls(); s.login(GMAIL, APP_PW)
        s.sendmail(GMAIL, t["to"], msg.as_string())
    print(f"SENT  {t['company']:25s} → {', '.join(t['to'])}")

sent = 0
for t in TARGETS:
    try:
        send(t)
        sent += 1
    except Exception as e:
        print(f"FAIL  {t['company']}: {e}")

print(f"\nRe-sent {sent}/{len(TARGETS)} with cv_main_generic.pdf")
