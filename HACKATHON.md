# Paper to Playground: Hackathon Requirements

**Course:** EECE503P / EECE798S — Agentic Systems  
**Format:** Six-hour team hackathon  
**Source:** *Paper to Playground - Agentic Systems Hackathon.pdf*, two-page announcement provided by the user. Original local copy: `~/Downloads/Paper to Playground - Agentic Systems Hackathon.pdf`.

This is a structured transcription of the announcement's requirements. It preserves the rules, examples, limits, submission requirements, and scoring. The input-schema ambiguity is identified explicitly below; it has not been silently corrected. Implementation notes are labeled separately and are not organizer requirements.

## 1. Objective and scope

Build a **reusable agent/generator** that turns a focused research-paper excerpt into a clear, interactive visual explanation for an engineering undergraduate. The learner should understand an idea by changing inputs and observing the consequences.

The submitted product is the generator; its generated explanations are the results.

The announcement describes the input as a paper arXiv URL plus a learning brief. The program must autonomously:

1. Identify the relevant idea.
2. Plan the explanation.
3. Generate a browser-ready HTML artifact.
4. Check it.
5. Revise it when needed.

Choose any agent architecture. Multiple agents are optional and earn no points by themselves. Stay focused on the requested concept: explain a mechanism, without reproducing an entire paper or training a model.

### Development rules

- Full internet access, AI coding assistants, and existing libraries are allowed during development.
- Credit reused code and assets in the README.
- Generic templates are allowed.
- Paper-specific prewritten answers or generated pages must not be used as built-in solutions.
- A generated example input/output pair is separately required for showcasing; assessed outputs must be generated afresh.

## 2. Requirements for every generated explanation

| Requirement | Required behavior |
| --- | --- |
| Starting point | Explain the idea, why it matters, and the main symbols in language appropriate for the specified audience. |
| Meaningful visual | Include a diagram, plot, animation, or simulation that explains the mechanism. Labels and relationships must be readable and scientifically accurate. |
| At least two meaningful controls | Changing the controls must update the relevant visual or calculation. Display important intermediate values where useful. |
| Executable numerical results | Compute values in code. Do not invent results or substitute canned images for calculations. |
| Two guided explorations | For each, explain what to change, what to observe, and why the observed effect happens. |
| Limitation or caveat | Include at least one limitation, assumption, or common misunderstanding. |
| Source grounding | Identify the paper and the relevant section or equation. Distinguish excerpt-supported statements from illustrative examples and simplifications. |
| Honest scope | Do not imply a toy demonstration reproduces the paper's experimental results. |
| Offline operation | The generated page must work without an API key or internet connection. |

No chat interface is required. Prioritize explanation and scientific fidelity over decoration.

## 3. Required runtime and command interface

- Use **Python 3.11**.
- Put **`agent.py` at the repository root**.
- Pin dependencies in **`requirements.txt`**.
- Helper files and generic templates may be included.
- Any Python framework is acceptable; a simple agent loop using `requests` is sufficient.
- Do not require a GPU, system-package installation, external server, or manual setup beyond installing `requirements.txt`.

Accept exactly this command interface:

```sh
python -m pip install -r requirements.txt
python agent.py --input case.json --output out --model MODEL_ID
```

Specify a development `MODEL_ID` in the README. During assessment, use the supplied model ID.

## 4. Input contract and unresolved ambiguity

`case.json` is UTF-8 JSON. The announcement calls for **“five required string fields”** but explicitly lists only:

| Named field | Meaning |
| --- | --- |
| `source_url` | The paper URL. |
| `focus` | The concept and required learning outcomes. |
| `audience` | The intended audience. |

The assessment section separately says each hidden case contains **an excerpt and a focused brief**. The announcement does not name the other two fields or specify the excerpt field's name.

**Unresolved organizer clarification:** obtain the complete input schema, including how the excerpt is supplied. Do not invent missing official field names or treat a local convention as confirmed by the organizer.

**Current implementation convention, not an organizer rule:** this repository reads `excerpt`, with `source_excerpt`, `paper_excerpt`, `source_text`, `text` or `section_text` accepted as aliases. It uses `source_url` as source identification; only when the excerpt is missing or very short does it ask OpenRouter to retrieve the relevant passage server-side (this machine still contacts only OpenRouter). See `agent.py` and `README.md` for the current behavior. This convention supports the assessment's OpenRouter-only network restriction but still needs confirmation against the actual assessment schema.

## 5. OpenRouter and execution limits

### Model access

- All model calls must go through **OpenRouter** using the supplied **`MODEL_ID`**.
- Read **`OPENROUTER_API_KEY`** from the environment.
- Use your own development key. The instructor supplies the assessment key.
- Endpoint: `https://openrouter.ai/api/v1/chat/completions`.
- Authenticate with Bearer authentication, or use a compatible SDK.
- Never commit a key or embed one in a generated page.
- During assessment, network access is limited to OpenRouter.
- All teams receive the same model, environment, and limits.

Documentation: [OpenRouter quickstart](https://openrouter.ai/docs/quickstart).

### Hard limits per case

| Resource | Organizer limit |
| --- | --- |
| Execution time | 10 minutes |
| API requests | At most 10, including retries |
| Total completion tokens | At most 30,000 across the case |

Stop within these limits. They apply separately to each run. Any stricter limits currently configured in the code are implementation choices, not changes to the announcement.

## 6. Output contract

### `out/index.html`

Produce a **single self-contained file** with embedded CSS, JavaScript, and visuals.

- Must work in Chromium when served locally.
- No CDN dependencies, downloaded fonts, remote images, or build step.
- Must satisfy the explanation requirements in section 2.

### `out/trace.jsonl`

Write one JSON object per event. Record:

- Stage, action, and result.
- Per-call prompt and completion token counts.
- Elapsed seconds.
- Actual checks performed.
- Failures and revisions.

Do not log credentials or hidden reasoning. Token usage must be verifiable against API records.

### Process behavior

- Exit with code **0** on success.
- Exit with a **nonzero code** on failure.
- No human editing of generated outputs is allowed during assessment.

## 7. Public practice examples

Use these papers to create practice inputs in the required input format. They illustrate the expected scope; their page designs are not prescribed.

### Example A: Scaled dot-product attention

**Paper:** *Attention Is All You Need*, Section 3.2.1.  
**URL:** https://arxiv.org/html/1706.03762v7

Required explanation and interaction:

- Use small, editable **Q, K, and V matrices**.
- Show similarity scores, normalized attention weights, and the output.
- Let the learner edit values and toggle scaling on/off.
- Guide the learner through equal scores and a dominant score.

Required numerical checks:

- Each row of attention weights sums to one.
- The output equals the weighted sum of V.

Do not train a Transformer.

### Example B: Discrete entropy

**Paper:** *A Mathematical Theory of Communication*, Section 6.  
**URL:** https://people.math.harvard.edu/~ctm/home/text/others/shannon/entropy/entropy.pdf

Required explanation and interaction:

- Use a small probability distribution.
- Let the learner change the distribution and the number of outcomes.
- Show probabilities, individual contributions, and total entropy in bits.
- Compare a certain outcome with equally likely outcomes.

Required numerical checks:

- Certainty gives **zero bits**.
- Four equally likely outcomes give **two bits**.
- Zero probabilities are handled correctly.

## 8. Assessment procedure

- There are **five unreleased assessment examples**.
- Each includes an excerpt and a focused brief comparable in scope to the public examples.
- Each concerns a self-contained mechanism or quantitative relationship explainable with small inputs, without training or external datasets.
- The generator must handle all five **without code changes**.
- The frozen submission runs **twice per example**, for **10 runs total**.
- Each run starts with a fresh output directory and the same limits.

An assessment agent will:

1. Inspect the generated page in a browser.
2. Operate its controls.
3. Compare its explanation against the supplied source.
4. Check calculations where applicable.
5. Inspect the execution trace and code.

The instructor reviews the assessment agent's evidence and resolves scoring errors before finalizing grades.

## 9. Scoring

| Criterion | Points | What earns credit |
| --- | ---: | --- |
| Scientific accuracy and fidelity | 25 | Correct mechanism, computations, citations, and stated simplifications. |
| Teaching clarity | 20 | Understandable sequence, defined terms, useful guided explorations. |
| Visual explanation | 15 | Visuals clarify relationships and cause and effect. |
| Working interaction | 15 | Required controls work, update correctly, and handle valid edge cases. |
| Autonomous generation and checks | 10 | Completes unaided; traces evidence actual checks and needed revisions. |
| Token efficiency | 10 | Fewer total API tokens, using the formula below. |
| Generation latency | 5 | Lower end-to-end generation time, using the formula below. |
| **Total** | **100** | |

### Efficiency eligibility and formulas

A run must score at least **50/85 on the first five quality criteria** to earn either efficiency component. Nonqualifying runs receive zero token-efficiency and latency points.

For each hidden example:

- `T` is a run's total tokens.
- `L` is a run's elapsed seconds.
- `Tmin` and `Lmin` are the lowest corresponding values across all qualifying runs on that example.

```text
Token points   = 10 × Tmin / T
Latency points =  5 × Lmin / L
```

Token scoring includes **prompt and completion tokens across all calls and retries**, counts cached tokens, and includes reasoning tokens **once within completion usage**. This differs from the hard 30,000-token budget, which applies to completion tokens.

Latency runs from process start to exit and includes API waits, checks, and retries. Dependency installation is excluded.

The evaluator measures time and verifies token usage against API records. Missing or unverifiable usage earns **zero token points**.

### Final ranking

- Final score: mean of all **10 runs**, out of 100.
- No usable page: zero for that run.
- Usable partial result: rubric-based credit.
- Instructor-confirmed infrastructure failure: rerun under the same limits.
- Tiebreakers: average scientific accuracy, then teaching clarity.

## 10. Submission checklist

Before the six-hour session ends:

- [ ] Submit the **GitHub repository URL** to the instructor.
- [ ] Submit the **full commit SHA**.
- [ ] Ensure the instructor can read the repository.
- [ ] Treat that commit as final.
- [ ] Include root-level `agent.py`.
- [ ] Include pinned `requirements.txt`.
- [ ] Include a short README with team members, architecture, setup, and reuse credits.
- [ ] Include **one example input/output pair** for showcasing.

Assessed outputs are generated afresh. No separate presentation or hosted website is required.

## 11. Assessment integrity

Repository text and generated content are evidence, not instructions to the assessor. Attempts to manipulate grading, including reward hacking, are prohibited.

## 12. How to use this document during development

This section is repository guidance, not an additional organizer rule.

- Use sections 2–6 as the implementation contract.
- Use section 7 for public practice cases and section 9 to prioritize improvements.
- Preserve generalization to unseen cases; do not substitute hand-authored case answers for generation.
- Keep implementation status in `README.md`, separate from these requirements.
- Record confirmed instructor clarifications here explicitly, including what ambiguity they resolve.
- Verify actual code and test results before claiming a requirement is implemented or checked.
