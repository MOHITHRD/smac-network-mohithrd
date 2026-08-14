# Tool descriptions - v1 and v2

**The specification requires two versions of every domain tool description.**
Only **v2** is served live, in your docstring. **v1** lives here, and is submitted
with your final report.

Fill this in as you go. If you skip it and only write v1 here at the end, you will
be reconstructing it from memory - and it shows.

---

## Why this file exists

The Orchestrator never reads your code. Choosing whether to call you, it sees
**only your tool name, your description, and your parameter descriptions**. That
text is the whole interface, and it is graded.

Writing a better description is the cheapest, highest-leverage improvement
available to anyone in this theme regardless of programming background - and the
v1/v2 pair is the built-in before/after dataset for **ablation option 3 (tool
schema & description design)**.

---

## What makes v2 better than v1

A useful description covers four things:

1. **What it does**, concretely - not "handles charging queries".
2. **Coverage** - where your answers are valid.
3. **Freshness** - how live the data is.
4. **What it does *not* do.** The most-skipped and most valuable: it stops the
   Orchestrator calling you for questions you would answer badly.

Describe every parameter too - those are the instructions for filling in your
tool:

```python
lat: Annotated[float, Field(description="WGS84 latitude of the trip origin.")]
```

A revision is only worth recording if you can say **what evidence prompted it**.
"Sounded better" is not evidence. Real evidence looks like: it was selected for a
query it shouldn't have been; it wasn't selected for one it should have; a
parameter came back wrong; a peer's agent was chosen over yours.

---

## Tool 1 - `<tool_name>`

### v1 - initial draft
> _Paste your first description here, verbatim, before you start testing._

### v2 - refined (this is what's served live)
> _Paste the final version here. It must match the docstring in your agent._

### What changed and why

| # | Change | Evidence that prompted it |
|---|---|---|
| 1 | e.g. added "Covers South East Queensland only" | Orchestrator called it for a Cairns query and got a refusal |
| 2 | e.g. added "Does not report live availability or pricing" | It was selected over a fares agent for a cost question |
| 3 | | |

### Parameter descriptions

| Parameter | v1 | v2 |
|---|---|---|
| `lat` | | |
| `lon` | | |

---

## Tool 2 - `<tool_name>`

_(Copy the block above. Delete any tools you don't have - between 1 and 5.)_

---

## Worked example

Taken from the starter kit's charging tool, so you can see the shape.

### v1 - initial draft
> Find EV charging stations near a location in Queensland.

### v2 - refined
> Find the closest Queensland Electric Super Highway charging stations to a point.
>
> Answers range-planning questions for electric vehicle trips starting in South
> East Queensland - where the next public charging site is, how far away, and
> which sites lie onward along the highway network. Uses the Queensland
> Government's published station list, so it covers intercity corridors rather
> than every kerbside charger in a suburb.
>
> Origin must be in South East Queensland; returned stations may be anywhere in
> Queensland, since onward stations matter on long trips. Plug and connector
> types are NOT available - the source publishes that column empty. Does not
> report live availability or pricing, and does not plan a route.

### What changed and why

| # | Change | Evidence |
|---|---|---|
| 1 | Named the actual dataset ("Electric Super Highway") instead of "in Queensland" | 17 stations statewide - "near a location" implied dense urban coverage the data doesn't have |
| 2 | Stated origin must be in SEQ, results may be statewide | Ambiguity: the agent refuses Cairns *origins* but returns Cairns *stations* |
| 3 | Added "Plug and connector types are NOT available" | Source publishes that column empty; without this the Orchestrator routes connector questions here |
| 4 | Added "does not report live availability or pricing, does not plan a route" | Competing agents exist for cost and routing - this stops mis-selection |

Each row cites something observed rather than a preference. That table is what
you analyse in your report.
