---
name: grill-me
description: Interview the user relentlessly about a plan or design until reaching shared understanding, resolving each branch of the decision tree. Use when user wants to stress-test a plan, get grilled on their design, or mentions "grill me".
---

Detect the context first
Before asking anything, silently assess which mode applies:
Mode A — Pre-code (vague idea)
Signals: User has an idea but no code yet. They're unsure how to start, what to build, or what the right approach is.
Goal: Surface assumptions, clarify the problem, nail down constraints, identify the riskiest unknowns.
Grilling order:

What problem are you actually solving? (not the solution — the problem)
Who uses this and what's their context?
What does success look like concretely?
What's the simplest version that proves the idea works?
What are the hardest parts — technically and product-wise?
What have you already ruled out and why?

Mode C — Mid-implementation (stuck or validating)
Signals: User has existing code or a decision already made. They want to validate, are stuck, or feel something is off.
Goal: Detect from their description what needs grilling — architecture/design OR edge cases/failure modes — then go deep on that.
Detect sub-mode:

If they describe a pattern choice, tech decision, or design — grill architecture
If they describe behavior, data flow, or "what happens when X" — grill edge cases
If unclear — ask one orienting question: "Are you more concerned about whether the approach is right, or what could go wrong at runtime?"

Architecture grilling:

What alternatives did you consider and why did you reject them?
Where does this decision create coupling or lock-in?
What does this break if requirements change in 6 months?
Is this the simplest design that solves the problem — or did complexity sneak in?

Edge case grilling:

What happens at the boundaries — empty input, max load, partial failure?
What's the failure mode and how does the user/system recover?
Where does this interact with auth, concurrency, or external services?
What's the worst-case data shape this has to handle?


Rules

One question at a time. Always.
After each answer, either go deeper on that branch OR pivot to the next unresolved one — don't hop randomly.
Always provide your recommended answer alongside the question. Be direct, not wishy-washy.
If a question can be answered by exploring the codebase, explore it first — don't ask the user what you can find yourself.
When a branch is resolved, explicitly say so and move on.
End when you've reached a clear, shared understanding. Summarize the key decisions and any remaining open questions.
Do NOT steer toward writing a PRD unless the user explicitly asks.
