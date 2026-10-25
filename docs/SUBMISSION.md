# Submission text (copy-paste into the form)

## Project name

Virtual Lab

## Tagline (one line)

A lab of 28 Gemini agents that plans a study, runs it on real patient data, and has to beat Gemini 4 Argon answering alone.

## Description

Cancer researchers have public datasets and hypotheses, but getting from a question to a tested,
cited answer takes days: someone has to read the literature, design the analysis, poke holes in it,
then write and run the code. An AI chatbot answers in seconds, but it never touches the data, so its
numbers are educated guesses.

Virtual Lab works like a real lab, built from 28 Gemini agents with one job each. They study the
topic and write cited notes. Three planning meetings run in parallel: in each, a lead scientist asks
an immunologist, a statistician and a data expert for ideas, and a critic attacks the plan until it
holds up. A lead scientist merges the plans and code checks that the data has every variable needed.
Then a person approves the budget, which becomes a hard spending cap. Gemini 4 Argon writes the
analysis code, and a Gemini managed agent runs it on 1,980 real breast cancer patients (METABRIC) in a
Google-hosted sandbox. The lab writes an answer that separates what its data shows from what published
research says, with references. Finally a blind judge compares it with Gemini 4 Argon answering alone,
twice, with the order swapped; the lab must win both.

On our demo question (is more cytotoxic immune activity in triple-negative breast cancer linked to
longer survival, after accounting for age, stage and grade?), the lab won 10 of 11 blind tests. It found
about a 20% lower risk of death per standard deviation of the immune score (hazard ratio 0.76–0.80 in
every run), consistent with the literature. A run takes about 2.5 minutes and costs about $0.35.

It is a research tool, not medical advice: questions about an individual patient are turned into
research questions about patients in general, and it uses public data only.

## How we use Gemini

- **Gemini 4 Argon** is the lead scientist: it runs the planning meetings, plays the critic, merges the
  plans, writes the analysis code, writes the final answer and judges the blind test.
- **Gemini 3.8 Flash** plays the specialists and the study team, many at once; **Flash-Lite** routes and
  guards; **Gemma 4** writes a quick first draft that the lab later checks.
- **Gemini Managed Agents (Antigravity)**: a pre-warmed Google sandbox holding the patient data runs the
  analysis and repairs it if it fails, under the token budget the human approved. Each run is isolated.
- **Google Search grounding and Deep Research** find and cite the literature, saved as team knowledge.

## Describe your use of Google products

Virtual Lab runs entirely on Google’s Gemini platform, through the Gemini Interactions API (google-genai
Python SDK):

- **Gemini 4 Argon** is the lead scientist: it runs the three planning meetings, critiques each plan,
  merges them, writes the analysis code, writes the final answer, and acts as the blind judge. It also
  answers alone as the baseline the lab must beat.
- **Gemini 3.8 Flash** plays the specialists (immunologist, statistician, computational biologist) and the
  "school" that studies the topic, many calls in parallel. **Gemini 3.5 Flash-Lite** handles routing and
  the safety guard. **Gemma 4 (31B)** writes a quick first draft that the lab later fact-checks.
- **Gemini Managed Agents (Antigravity agent)** is the lab bench: a pre-warmed, Google-hosted sandbox
  holding 1,980 patient records. Argon’s code is uploaded with the Environments file API and run there;
  the agent repairs it if it fails. The budget a human approves is enforced as the agent’s
  `max_total_tokens` cap, and each run gets its own isolated folder.
- **Google Search grounding** and the **Deep Research agent** find and cite the published literature,
  which the lab saves as reusable team knowledge.
- **Gemini text-to-speech** (gemini-3.8-flash-tts) narrates our demo video.
- We built it with Google’s official **Gemini API skill** (gemini-api-dev) loaded into our coding agents,
  as the DeepMind builder guide recommends.

## What we built at the hackathon

All of the code, written on October 25: the 28-agent relay on the Gemini Interactions API, the
managed-agent analysis with the approval-set budget, a fast mode that took a run from 11 minutes to
2.5, a safety guard, the blind judge, a live web page that shows every hand-off, and 27 tests. Two
rounds of independent code review were fixed the same day.

Before the event our team had an earlier prototype of the idea (using Gemma and Claude); it never ran
code on data and lost its blind test. We kept the design and rewrote everything.

## Links

- Code (public): https://github.com/SankarSubbayya/virtual_lab
- Slides: docs/Virtual_Lab_slides.pdf in the repo
- Demo video: [paste the video link here]
