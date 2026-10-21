# Defense guide

What to say when someone pushes on this repository. Every number here is re-measured by
`make receipts` and checked against this document's wording, so if the code changes and
this file does not, the build fails.

## The one sentence version

A carrier on time in full scorecard measures from ship confirm to delivery, so every delay
that happened before ship confirm is outside the window it measures rather than measured
imprecisely by it. This package reconstructs the stages from the event log and attributes
each late delivery to the stage that produced it, including the two the scorecard cannot
see.

## Why this project exists

At Mahindra Logistics I ran lane analyses that compared carriers on transit performance,
and I could not have told you how much of the lateness our customers experienced happened
before the carrier ever collected the shipment. The scorecard did not have a term for it
and nobody asked. This is the tool that would have.

## The six questions I expect

### 1. "Isn't this just adding more stages to OTIF?"

No, and the difference matters. Widening the carrier's window to start at order creation,
which is sometimes proposed as door to door OTIF, makes the carrier accountable for the
warehouse, which no carrier will sign. It also still produces one number with no
attribution inside it.

The problem is not that the window is too narrow. It is that one number cannot carry three
causes. On this log, 71.9% of late deliveries were caused by a stage that ends before ship
confirm, and the same share arrives with the carrier inside its committed window, so every
one of them is recorded as a carrier success. Widening the window changes who gets blamed.
It does not say who should be.

### 2. "How do you know the attribution is right?"

Because the event log is generated with the cause of each late delivery written down, and
the attribution is graded against it with a confusion matrix across twelve independent
logs. That grading was written before any of the prose in this repository, which is not an
accident: a sibling project in this portfolio shipped a simulator that nothing graded, and
when its own stated grading criterion was finally pointed at it, it had been wrong from
the start.

The grading is also what found three defects here, and all three were in the generator
rather than the tool. Shipments labelled as on plan had drifted past a cutoff, so the
generator was producing a real missed cutoff and calling it nothing. Shipments labelled
infeasible plan had a departure wait that genuinely overran. Both appeared in the matrix
as misattributions when the label was the thing that was wrong. A recovery rate measured
against a mislabelled fixture grades the generator, not the tool.

### 3. "What is the weakest part of this repository?"

That the attribution cannot name a single cause reliably, and no version of it will.

The best convention recovers 72.4% of planted causes and the worst is down to 67.3%. The
reason is structural: 62.8% of late deliveries have more than one stage over plan, because
a release that overran by six hours has also missed the day's last departure. Both stages
are over plan. Both statements are true. `first_cause` recovers every warehouse overrun
and blames missed cutoffs on the warehouse too; `largest_cause` recovers every missed
cutoff and blames warehouse overruns on the departure wait, because a missed departure is
mechanically larger than the overrun that caused it.

So if someone wants a report naming one upstream team as the cause, this
tool will give them one and it will be wrong about a third of the rows.

What makes that tolerable rather than disqualifying is that the headline does not depend
on it. Both upstream stages lie outside the scorecard's window, so which one a convention
names cannot change how much the scorecard misses. The upstream share is identical under
all three conventions, and a test fails if that ever stops being true. The strong claim is
about how much is invisible; the scoped claim is about which team to talk to.

### 4. "What is this tool wrong about?"

Three things I would say before being asked.

It refuses shipments whose timestamps are out of order rather than repairing them, and
that refusal is a selection effect nobody has measured. If chaotic shipments attract manual
intervention, which is plausible, then refusing them biases the attribution toward the
shipments that went smoothly. The fixture produces none, so this repository cannot measure
the bias and does not pretend to. It is the first thing to check against a real log.

The counterfactual departure charge assumes a fixed, known departure schedule. A lane where
a shipment can be re-planned onto a different service has no single departure it would have
caught, and the charge is undefined there.

And the absolute shares follow from the planted cause mix. That the upstream share is not
zero, and not visible from a scorecard, is general. That it is 71.9% is a fact about this
log.

### 5. "Walk me through a bug you found."

The departure charge, which I got wrong twice in different directions.

The first version charged the whole release to departure wait. That blames the warehouse
for the timetable: a shipment released at 06:00 on a lane whose only departure is at 16:00
waits ten hours and did nothing wrong.

The second version charged the wait above a fixed handling floor, subtracting the time
every shipment needs between release and departure. Better, and still wrong, because an
early release can land in an unlucky part of the day just as easily as a late one.

The confusion matrix caught it rather than review. Shipments whose planted cause was an
infeasible plan, meaning every stage inside its plan and a promise the plan never reached,
were being attributed to a departure wait they had not caused, in a matrix that existed
precisely to catch this.

The fix is a counterfactual: the departure this shipment actually caught, against the
departure it would have caught had it released on plan. A release that misses nothing costs
nothing, however long it then waits, and a release five minutes late that misses the day's
last departure costs the entire gap to tomorrow's. ADR-003.

### 6. "What would you build next, and what did you deliberately leave out?"

Left out: telling anyone what to fix. Once the stages are attributed the obvious next step
is to rank interventions, move the cutoff an hour later, add a second departure, tighten
the pick line. Ranking them needs the cost of each, and this repository cannot measure what
a later cutoff costs to negotiate or what a second departure costs to run. Putting invented
costs inside a ranking would make the planner's hardest judgement for them in the place
they would be least likely to find it.

I also went looking for a stronger claim and did not find it. I expected that fixing the
attribution would change which carrier looks worst, the "you fired the wrong carrier"
finding. On this fixture the lane with the worst delivered service also has the worst
carrier, so that claim is not supported and is not made. What the measurement does support
is weaker and better: carriers on lanes with different departure frequency are not
comparable at all.

Next, in order: more lanes so the comparability finding becomes a correlation rather than
three rows; out of order timestamps in the generator so the selection effect becomes
measurable; and promise setting as its own stage, since infeasible plans are 11.6% of late
late deliveries here and the tool currently says only that the plan was the problem.

## Numbers I should know cold

- **71.9% of late deliveries** were caused by a stage that ends before ship confirm, with
  an sd of 0.96 points across twelve logs. The same share arrive with the carrier inside
  its window.
- The scorecard is right **92.6% of the time** about what it flags and **sees 28.1%** of
  the late deliveries. Precise and blind is the harder failure to notice.
- **62.8% of late deliveries have** more than one stage over plan, which is why the best
  convention only **recovers 72.4%** of planted causes and the worst is **down to 67.3%**.
- A single departure lane runs **36.8% late on** delivered service against **22.8% on the three**
  departure lane, with identical carriers, and the carrier accounts for **24.4% of
  its own lateness** there against **40.1% on the lane with three**.
- A daily clock **loses 51% of** the late deliveries and the rounding rule alone **swings
  the count by 54%**. An hourly clock **shifts it by 0.11 points**.
- At 250 shipments the scorecard **flags 21 shipments**, a **floor of 5.09%**, and the
  precision claim needs about 2000 shipments to separate.
- **181 tests**, **100% line coverage**, over a fixture of **2000 shipments** across
  **3 lanes**.

## If someone says this is just event log analysis

They are right that reconstructing stages from timestamps is not a novel technique. The
contribution is not the reconstruction.

It is noticing that a metric used everywhere in transport has a window that structurally
excludes most of what it is used to judge, measuring the exclusion on a log where the
answer is known, showing that the exclusion makes carriers on different lanes incomparable,
and then being honest that the natural follow on question, which upstream team to blame,
cannot be answered reliably at all.

Knowing which standard technique applies to a messy operational question, and knowing what
it cannot do, is the job.
