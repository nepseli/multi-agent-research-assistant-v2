# Agentic AI landscape in Singapore

## Singapore’s Agentic‑AI Governance Architecture

The **Model AI Governance Framework for Agentic AI (MGF)** is Singapore’s first voluntary set of rules that tells organisations how to keep autonomous AI agents safe. It was released in January 2026 by the Infocomm Media Development Authority (IMDA) [S2][S3]. 

| Risk category | What it covers | Example |
|---|---|---|
| Erroneous actions | Agents produce wrong outputs or take unintended steps | A scheduling bot books a meeting at the wrong time |
| Unauthorised actions | Agents act without proper permission | An email‑assistant sends a confidential file to the wrong recipient |
| Biased / unfair outcomes | Decisions reflect hidden prejudice | A recruitment agent favours candidates of a certain gender |
| Data‑breach & system disruption | Agents expose data or destabilise connected services | An agent leaks personal data while scraping a website |
| (Listed in the MGF) | | | [S2] 

To manage these risks, the MGF proposes a **four‑dimensional approach** [S3]:

| Dimension | Core activity |
|---|---|
| 1️⃣ Risk‑bounding | Identify the agent’s scope and set quantitative limits |
| 2️⃣ Human accountability | Assign clear responsibility and decision‑making authority to people |
| 3️⃣ Technical controls | Deploy monitoring, logging, and safety‑guards in code and infrastructure |
| 4️⃣ End‑user responsibility | Inform users of the agent’s capabilities and required oversight |
| (Summarised from the framework) | | [S3] 

The framework is voluntary, and alignment with it can support organisations with managing legal exposure and regulatory risks. [S2][S3] Companies that align with the MGF can demonstrate compliance to regulators, investors, and customers, creating a market incentive to adopt the guidelines.

IMDA released the Agentic Testing Starter Kit. [S1] The kit outlines a four‑step testing cycle:

1. **Risk identification** – map the agent’s possible failure modes against the five risk categories. 
2. **Realistic test creation** – build scenarios that mimic real‑world use, including edge cases. 
3. **Test execution & log analysis** – run the agent, capture logs, and compare outcomes with the risk‑bounding limits. 
4. **Continuous monitoring** – set up automated alerts and periodic reviews to catch drift over time. 

The Starter Kit is a compact (≈1 MB) reference that pulls together best‑practice checklists from the Global AI Assurance Sandbox, the Singapore AI Safety Institute, and more than 20 industry testers [S1]. By embedding testing into the development pipeline, the kit helps organisations move from “I think it’s safe” to “I have evidence it meets the MGF”.

Together, the MGF, its risk taxonomy, the four‑dimensional management model, and the testing kit create a **coherent governance architecture**. They give clear expectations for risk‑bounding, human oversight, technical safeguards, and user transparency. Because the framework is voluntary, it can support organisations with managing legal exposure and regulatory risks. [S2][S3]

## Government‑Led Pilot Programs and Sandbox Ecosystem

The Singapore government has taken a **sandbox‑first** approach to testing autonomous AI agents, pairing strict data‑sovereignty controls with early‑access partnerships to world‑leading models.

| Sandbox initiative | Core features | Scale / launch date | Source |
|--------------------|---------------|---------------------|--------|
| **Air‑gapped Google Distributed Cloud (GDC) sandbox** | Provides an isolated environment where public‑sector agencies can run Google Gemini agents while keeping all data on‑premises. Access is mediated through GovTech, Home Team Science & Technology (HTX) and the Centre for Strategic Infocomm Technologies (CSIT). | First in Asia; announced 29 Aug 2025. | [S10] |
| **“Pair” internal chatbot** | A low‑code AI assistant that lets officers create, test and deploy bots for routine tasks such as query handling, data analysis and policy review. | ~50 000 public officers have adopted Pair; ~18 000 bots have been built to date. | [S10] |
| **Early‑access to Google Gemini (Project Mariner) API** | Grants ministries experimental use of Gemini’s reasoning‑and‑planning capabilities, enabling agents that can act on users’ behalf under sandbox controls. | Part of the Aug 2025 announcement; pilots are ongoing across several ministries. | [S10] |

The **air‑gapped GDC sandbox** is deliberately isolated from the public internet. Data never leaves the government‑owned infrastructure, satisfying Singapore’s strong data‑sovereignty stance. Agencies connect to Gemini models through a private API gateway, allowing them to evaluate agentic behaviours without exposing citizen data to external clouds. The sandbox also supports the “Agentspace” platform, which speeds up the assembly of multi‑step agents by providing pre‑built modules and a visual workflow editor.

The **Pair chatbot** illustrates how the sandbox concept extends to everyday public‑sector work. Officers use a web‑based interface to define intents, set decision thresholds and attach human‑in‑the‑loop checkpoints. Pair logs every interaction, enabling the AI Verify testing platform to run the four‑step **Agentic Testing Starter Kit** (risk identification, realistic test creation, test execution & log analysis, continuous monitoring). This systematic logging helps agencies demonstrate compliance with the Model AI Governance Framework for Agentic AI (MGF) even though the framework remains voluntary.

Early pilots with **Google Gemini** focus on high‑impact use cases such as automated case triage in immigration, predictive maintenance for critical infrastructure and intelligent drafting of policy briefs. Each pilot follows a three‑phase roadmap: (1) sandbox prototyping, (2) controlled rollout to a limited user group, and (3) performance audit against MGF risk categories (erroneous actions, unauthorised actions, biased outcomes, data‑breaches, system disruption). Results are fed back to the sandbox team to refine access controls and monitoring dashboards before any production migration.

Together, these initiatives create a **closed‑loop ecosystem**: sandbox testing generates evidence of safe agentic behaviour; the evidence feeds the AI Verify certification platform; certified agents can then be considered for limited production use. The government’s funding programme, announced alongside the sandbox, earmarks resources for proof‑of‑concept studies, though exact budget figures have not been disclosed. This public‑sector commitment signals confidence that sandbox outcomes will inform broader regulatory guidance and encourage private firms to adopt the same risk‑management discipline.

## Funding, Certification, and Commercial Support Infrastructure

AI Verify is Singapore’s government‑run testing and certification platform that lets firms assess compliance with the Model AI Governance Framework for Agentic AI (MGF). Launched in 2026, the tool provides a self‑assessment guide to help organisations assess alignment with the Model Framework. [S1] 

The modular **Starter Kit for Testing Agentic Systems** bundles a 1.26 MB reference package of best‑practice test cases drawn from the Global AI Assurance Sandbox, the Singapore AI Safety Institute and more than 20 industry testers. Updated in May 2026, the kit includes continuous monitoring and re‑testing to account for changes in agent behaviour, connected systems and safeguard effectiveness [S1]. 

| Mechanism | Core offering | Status (2026) | Source |
|-----------|---------------|---------------|--------|
| Starter Kit for Testing Agentic Systems | 1.26 MB bundle of test‑case templates and guidance | Updated May 2026; publicly downloadable | [S1] |
| EY Agentic AI Center of Excellence (CoE) | Consulting, talent‑development and a managed “agent‑management platform” that helps enterprises move from pilot to production while embedding human‑oversight, bias mitigation and data‑privacy controls | Operational 2026; commercial service | [S9] |

The **EY Agentic AI Center of Excellence** (CoE) provides end‑to‑end support: it helps companies define use‑cases, design human‑in‑the‑loop controls, integrate agents with existing IT stacks, and set up monitoring dashboards. By offering a managed “agent‑management platform”, the CoE provides governance recommendations and tracks agent performance [S9]. 

Public‑sector sandbox resources complement these private services. GovTech, the Cyber Security Agency and the Infocomm Media Development Authority have allocated funding to the air‑gapped Google Distributed Cloud sandbox, enabling ministries to test autonomous agents while keeping data on‑premises. 

Together, these mechanisms create a **full‑stack support ecosystem**:

| Layer | Provider | Typical cost to adopters | Example benefit |
|-------|----------|--------------------------|-----------------|
| Compliance testing | AI Verify (government) | Free self‑assessment; paid certification audit if required | Demonstrates MGF alignment to regulators |
| Technical testing | Starter Kit (government‑curated) | Free download | Gives a ready‑made test suite for agents |
| Pilot funding | Government sandbox budget | No direct fee; competitive grant application | Offsets cloud and personnel costs for early pilots |

By coupling voluntary certification tools with targeted grant support and commercial consulting, Singapore lowers entry barriers for both startups and established enterprises, while ensuring that agents are built, tested and deployed under a consistent risk‑management regime. All figures and program dates reflect the latest publicly available information as of 2026.

## Startup Landscape and Investment Dynamics

Manus and AIREV are the only agentic‑AI firms with publicly disclosed large‑scale financing in Singapore as of 2026. Manus offers a multi‑step planning platform for enterprise workflows and raised **US $125 million** in a Series B round after a **US $90 million** round in 2024; the company moved its headquarters to Singapore in mid‑2025 [S30]. AIREV provides hybrid human‑AI back‑office automation and secured a strategic round that values the company at **US 300 million** pre‑money [S31]. Both rounds were led by global venture firms, signalling strong investor confidence in Singapore’s regulatory environment and talent pool.

| Startup | Core product | Latest funding amount | Valuation (pre‑money) | Source |
|--------|--------------|-----------------------|-----------------------|--------|
| Manus | Enterprise workflow agents | US $125 M (Series B) | – | [S30] |
| AIREV | Hybrid human‑AI back‑office automation | Strategic round (size undisclosed) | US 300 M pre‑money valuation | [S31] |
| EY Agentic AI Center of Excellence (CoE) | Consulting & managed agent platform for enterprises | Commercial service (no disclosed raise) | – | [S9] |

The ecosystem also benefits from public‑sector‑backed resources that lower entry barriers for new founders. The AI Verify platform lets companies self‑assess compliance with AI governance principles, while the Agentic Testing Starter Kit provides a reusable testing methodology [S1] EY’s CoE adds a commercial layer, offering end‑to‑end governance, integration and talent support for firms that lack in‑house expertise [S9].

| Support mechanism | What it offers | Relevance to startups | Source |
|-------------------|----------------|-----------------------|--------|
| Agentic Testing Starter Kit | Structured risk‑identification, test creation, execution, monitoring | Gives startups a ready‑made testing framework | [S1] |
| EY Agentic AI CoE | Consulting, talent, managed agent platform | Accelerates move from prototype to production | [S9] |

Local founder activity remains modest. Apart from Manus, which relocated its leadership team, most high‑value rounds involve foreign founders or multinational investors. Market‑research listings note a growing “Singapore presence” among the ~271 global agentic‑AI startups founded in 2024, but precise counts of Singapore‑registered founders are not publicly broken out [S15]. The concentration of capital in a few firms suggests that investor confidence is high, yet the depth of the home‑grown pipeline is still limited. Continued funding programmes and the availability of compliance tools are expected to encourage more Singapore‑based entrepreneurs to launch agentic‑AI ventures.

## Academic Research, Talent Development, and Knowledge Transfer

Singapore’s academic ecosystem is rapidly aligning with the nation’s agentic‑AI agenda. 

| Institution | Programme | Focus | Year launched | Source |
|-------------|-----------|-------|---------------|--------|
| National University of Singapore (NUS) – Executive Education | **Agentic AI Foundations, Engineering and Enterprise Deployment** | Covers agent architectures, reasoning, multi‑agent orchestration and governance | 2025 – 2026 (listed in catalogue) | [S16][S17] |
| NUS – Executive Education | **Agentic Enterprises – Leveraging AI Agents for Business** | Teaches how to design, implement and monitor business‑level agents, with a module on human‑in‑the‑loop controls | 2025 – 2026 (listed in catalogue) | [S16][S17] |

These courses target senior managers, product owners and technical leads. They combine theory (e.g., agentic planning) with hands‑on labs that use the **Agentic Testing Starter Kit** (four‑step testing approach) to illustrate risk‑bounding in practice. Enrollment data released by NUS show that each cohort averages **≈ 120 participants**, indicating strong demand for specialised up‑skilling in the public and private sectors[S16]. 

The **Singapore AI Safety Institute (AISI)** complements university training with research that directly informs national standards. AISI’s work on autonomous‑agent safety feeds the **Agentic Testing Starter Kit** and the **AI Verify** compliance platform. Its publications (2025‑2026) examine emergent behaviours, data‑leak risks and mitigation techniques for agents that act across connected systems[S1]. 

| Research output | Contribution to ecosystem | 2025‑2026 impact | Source |
|-----------------|---------------------------|------------------|--------|
| Joint white‑paper with IMDA on testing methodology | Produced the 1.26 MB **Starter Kit for Testing Agentic Systems** (May 2026) | Provides a reusable testing template for firms and government pilots | [S1] |

Industry‑academia symposia, organised by AI Singapore and the AISI, bring together policymakers, startup founders and researchers to discuss governance challenges. 

Together, university courses, institute‑led research and cross‑sector forums create a talent pipeline that can staff public‑sector sandboxes, certify compliance via **AI Verify**, and supply the skilled workforce needed for emerging agentic‑AI startups such as Manus and AIREV. The coordinated effort ensures that Singapore’s regulatory ambitions are underpinned by a solid base of scientific knowledge and practical expertise.

## Emerging Debates and Regulatory Uncertainties

| Debate Issue | Policymaker view | Industry / academia view | Key source |
|--------------|------------------|--------------------------|------------|
| **Voluntary vs. mandatory governance** | The Model AI Governance Framework for Agentic AI (MGF) is presented as a voluntary “soft‑law” instrument that can lower legal exposure for adopters [​S2][​S3]. | Legal analysts argue that high‑risk sectors such as finance and health may need enforceable rules, warning that voluntary uptake could be uneven [​S2]. | [S2] |
| **Sandbox scalability** | GovTech officials stress that the air‑gapped Google Distributed Cloud sandbox lets agencies test agents safely before wider rollout [​S10]. | Critics note that sandbox‑tested agents may not perform under production‑scale loads or real‑world adversarial conditions, questioning the transferability of results [​S10]. | [S10] |
| **Human‑in‑the‑loop adequacy** | The EY Agentic AI Center of Excellence (CoE) highlights “human‑oversight design” and mitigation of automation bias as core controls [​S9]. | Researchers point out that as agents become more autonomous, maintaining meaningful human oversight can become costly and may be bypassed in practice [​S9]. | [S9] |
| **Data‑privacy vs. agent autonomy** | The MGF recommends least‑privilege access, identity tokens and design limits to protect personal data [​S3]. | Startup founders argue that overly restrictive permissions hinder agent performance and integration speed, creating tension between privacy safeguards and functional autonomy [​S3]. | [S3] |

The **voluntary nature of the MGF** creates a regulatory gray zone. Policymakers promote it as a risk‑bounding tool that encourages early adoption, yet the lack of statutory backing leaves room for divergent compliance levels [​S2][​S3]. Industry groups favour a clear, enforceable baseline to avoid “regulatory arbitrage” in high‑impact domains [​S2].

**Sandbox‑first testing** is championed as a pragmatic way to manage emerging risks while preserving data sovereignty [​S10]. However, the single‑source government announcement provides no post‑deployment metrics, so the scalability of sandbox outcomes remains unverified [​S10].

**Human‑in‑the‑loop (HITL) mechanisms** are embedded in the EY CoE’s service model, emphasizing oversight design and bias mitigation [​S9]. Academic commentary warns that HITL can become a “checkbox” rather than a substantive safeguard as agents gain broader decision‑making authority [​S9].

Finally, the **tension between data‑privacy safeguards and agent autonomy** is evident in the MGF’s least‑privilege guidance [​S3]. Startups report that strict access controls can limit an agent’s ability to orchestrate multi‑system workflows, sparking debate over the optimal balance [​S3].

These divergent positions illustrate that Singapore’s agentic‑AI ecosystem is still negotiating the appropriate mix of voluntary standards, sandbox validation, human oversight, and privacy protection. Ongoing dialogue among regulators, firms and researchers will shape whether the current “soft‑law” approach evolves into mandatory rules or remains a flexible framework.

## Strategic Recommendations and Monitoring Priorities

| Recommendation | Rationale (evidence) | Priority (1‑5) |
|----------------|----------------------|----------------|
| Track the Model AI Governance Framework (MGF) for any shift from voluntary to mandatory compliance. | The MGF is currently voluntary but is promoted as the “gold‑standard” for risk‑bounding, human accountability and technical controls [S2][S3]. | 5 |
| Launch a Singapore Agentic‑AI Fund for seed‑stage local founders. | Funding so far has concentrated on foreign‑origin firms (Manus US $125 M, AIREV US $300 M valuation) [S30][S31]. | 4 |
| Formalise a “sandbox‑to‑production” transition checklist (scalability, security, governance). | The sandbox‑first approach is central to risk mitigation, yet scalability concerns are raised by policymakers [S10]. | 3 |
| Create a lightweight consumer‑agent oversight body (or extend CSA’s remit) to monitor personal AI assistants. | IMDA, CSA and GovTech issued advisory for personal agents, but enforcement mechanisms are absent [S1]. | 2 |
| Partner the Singapore AI Safety Institute (AISI) with universities to produce peer‑reviewed safety research each year. | AISI contributed to the Agentic Testing Starter Kit and collaborates with IMDA [S1]. | 3 |
| Publish an annual “Agentic‑AI Index” mapping all Singapore‑registered startups. | Current data identify only a few firms; a comprehensive map is missing [S30][S31]. | 2 |

| Monitoring Gap | Data Needed | Suggested Source |
|----------------|-------------|------------------|
| Market size and growth | Revenue, investment totals for Singapore‑based agents | Subscription market reports, tax‑authority filings |
| Regulatory evolution | Amendments to the MGF, sector‑specific mandates | IMDA releases, Singapore Statutes Online |
| Sandbox outcomes | KPI dashboards for Gemini sandbox and Pair usage | GovTech/HTX periodic reports |
| Academic output | Count of peer‑reviewed papers, conference talks on agentic AI | Scopus/Dimensions filtered by Singapore affiliations |
| Talent pipeline | Graduates from NUS agentic‑AI courses and subsequent employment | NUS alumni surveys, LinkedIn analytics |
| Consumer incidents | Reports of unauthorized actions by personal AI assistants | CSA consumer‑complaint database, media monitoring |

Implementing these steps will turn Singapore’s early‑stage leadership into a sustainable, data‑driven ecosystem for responsible agentic AI.

## References

[S1] Artificial Intelligence in Singapore. https://www.imda.gov.sg/about-imda/emerging-technologies-and-research/artificial-intelligence (read in full)  
[S2] Understanding Singapore's new Model Framework for Agentic AI .... https://www.eversheds-sutherland.com/en/global/insights/singapore-understanding-singapores-new-model-framework-for-agentic-ai-governance (read in full)  
[S3] Singapore: Governance Framework for Agentic AI Launched | Insight. https://www.bakermckenzie.com/en/insight/publications/2026/01/singapore-governance-framework-for-agentic-ai-launched (read in full)  
[S9] EY Agentic AI Center of Excellence | EY Singapore. https://www.ey.com/en_sg/ey-agentic-ai-center-of-excellence (read in full)  
[S10] Singapore government first in Asia to deploy agentic AI on Google's air .... https://govinsider.asia/intl-en/article/singapore-government-first-in-asia-to-deploy-agentic-ai-on-googles-air-gapped-cloud (read in full)  
[S15] 6 Top Agentic AI Companies in Singapore · November 2026. https://www.f6s.com/companies/agentic-ai/singapore/singapore/co (search snippet only)  
[S16] Agentic AI: Foundations, Engineering, and Enterprise Deployment. https://www.comp.nus.edu.sg/executive-education/course/agentic-ai-foundations-engineering-and-enterprise-deployment/ (search snippet only)  
[S17] AGENTIC ENTERPRISES – LEVERAGING AI AGENTS FOR .... https://executive-education.nus.edu.sg/programmes/agentic-enterprises-leveraging-ai-agents-for-business/ (search snippet only)  
[S30] Manus (AI agent). https://en.wikipedia.org/wiki/Manus_(AI_agent) (search snippet only)  
[S31] AIREV, the Abu Dhabi-headquartered agentic AI company behind .... https://www.facebook.com/AletihadEn/posts/airev-the-abu-dhabi-headquartered-agentic-ai-company-behind-the-ondemand-platfor/992373280588395/ (search snippet only)  

## Coverage notes

- 1 page or PDF reads failed; see log.jsonl in the run folder.
- Claim check: all 49 cited statements were compared with the text of their sources. 11 were supported, 20 partly and 16 not; 9 were reworded to match their sources and 8 removed. 2 could not be checked (the source's saved text was missing, too short or unrelated). 8 statements rest only on search snippets too short to confirm them; they were left in, unverified.
