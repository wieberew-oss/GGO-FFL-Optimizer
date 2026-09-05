# FFL — Fantasy Football Helper App

## Project Goal

Build a private/personal **Streamlit fantasy football helper/optimizer** for a weekly fantasy football league that uses a salary-cap format similar to DraftKings Classic.

The app's primary purpose will be to take the weekly DraftKings player pool, combine it with useful NFL/player information, and help construct optimized lineups under the league's salary and roster constraints.

---

## League Format

The league operates on a **weekly salary-cap fantasy football format**.

### Salary Cap

* Total weekly payroll: **$50,000**
* Player salaries generally range from approximately **$2,500–$9,000**
* Each lineup must remain at or below the $50,000 salary cap.

### Roster

Each weekly lineup contains:

* QB — 1
* RB — 2
* WR — 3
* TE — 1
* FLEX — 1

  * RB, WR, or TE
* DST — 1

Total: **9 roster spots**

Example lineup supplied by the user:

| Position | Player        |
| -------- | ------------- |
| QB       | J. Herbert    |
| RB       | J. Cook III   |
| RB       | B. Irving     |
| WR       | D. London     |
| WR       | L. McConkey   |
| WR       | Rome Odunze   |
| TE       | D. Kincaid    |
| FLEX     | D. Montgomery |
| DST      | Buccaneers    |

The exact player pool and salaries will change each week.

---

# DraftKings Player Pool

The user can obtain the weekly DraftKings player pool as a CSV.

A relevant DraftKings URL discussed was:

`https://www.draftkings.com/lineup/getavailableplayerscsv?contestTypeId=21&draftGroupId=151307`

This appears to be the type of endpoint that provides the available-player CSV, but it was **not confirmed that the URL can be fetched programmatically without a DraftKings login/session**.

The preferred initial implementation should therefore support:

### Primary method

**Manual CSV import**

The user downloads the player pool CSV from DraftKings and uploads it to the Streamlit app.

This is preferable because:

* It is simple.
* It avoids dependence on undocumented DraftKings endpoints.
* It avoids authentication/session complications.
* It avoids building a scraper.
* The app can work with the exact player pool the user is actually entering that week.

### Possible future method

Investigate whether the DraftKings CSV URL can be retrieved programmatically.

Do **not** attempt to bypass authentication, anti-bot protections, or other access controls.

DraftKings' terms should also be checked before implementing automated collection/scraping. A manual CSV workflow is perfectly acceptable if automated retrieval is problematic.

---

# Proposed App

Working concept:

**Weekly Fantasy Optimizer**

Likely Streamlit interface:

1. Upload weekly DraftKings player CSV.
2. Parse player names, positions, salaries, teams, opponents, etc.
3. Add/enrich player information.
4. Generate projections.
5. Optimize lineups.
6. Display recommended lineups.
7. Explain why players were selected.
8. Allow different optimization strategies.

---

# Optimization Concepts

The app should eventually support several strategies rather than producing only one "best" lineup.

Possible modes:

### Best Projected Score

Maximize expected fantasy points while staying within the $50,000 cap.

### Best Value

Prioritize projected fantasy points relative to salary.

For example:

`Value = Projected Points / Salary`

or an equivalent normalized metric.

### High Floor

Favor players with more reliable expected production.

Useful when trying to minimize the risk of a poor weekly score.

### High Ceiling

Favor players with high upside.

Useful when trying to beat strong opponents.

### Balanced

Combine:

* projected points
* value
* floor
* ceiling
* matchup
* injury considerations

### Contrarian

Eventually incorporate projected ownership/popularity and deliberately avoid overly common combinations.

---

# Possible Player Data

The DraftKings CSV will primarily provide the weekly player pool and salary information.

The app could eventually enrich that data with:

* Recent fantasy performance
* Season averages
* Snap percentage
* Targets
* Carries
* Touches
* Red-zone usage
* Target share
* Receiving/rushing efficiency
* Opponent defensive statistics
* Vegas game totals
* Game spread
* Injury status
* Weather
* Home/away
* Expected game script
* Recent trends
* Player role changes

Potential external data sources discussed included:

* **nflverse** — useful for personal analytics and historical NFL datasets.
* **SportsDataIO** — commercial NFL/fantasy data.
* **Sportradar** — comprehensive professional-grade sports data.
* ESPN data/endpoints may also be useful, although the API situation is less clean/documented.

For an initial version, don't overcomplicate this. Get the CSV ingestion and optimizer working first.

---

# Monte Carlo / Simulation

A potentially valuable feature is using **Monte Carlo simulation** rather than relying solely on a single projected score.

For each candidate lineup, the app could simulate thousands of possible weekly outcomes based on uncertainty around each player's projection.

For example:

* Player A projection: 16 points
* Player A simulated outcomes might range from 5–30+
* Repeat across all players in a lineup.
* Run thousands of simulated weeks.
* Examine the resulting lineup distribution.

This could produce metrics such as:

* Expected score
* Median score
* 5th percentile
* 25th percentile
* 75th percentile
* 95th percentile
* Probability of exceeding a target score
* Probability of beating the league average
* Probability of beating a particular opponent

This would be particularly interesting for a salary-cap league because the goal isn't necessarily to find the lineup with the highest average projection.

---

# Opponent / League Analysis

A future feature could analyze historical lineups from the user's league.

If previous weekly lineups can be collected, the app could potentially learn:

* Players opponents tend to select
* Teams/positions they favor
* Typical salary allocation
* Risk tolerance
* Whether opponents tend toward chalk/popular players
* Historical lineup scores
* Individual opponent tendencies

That could eventually allow the optimizer to consider the **specific league environment**, rather than treating the problem as a generic DraftKings contest.

This should be considered a later-stage feature, not required for the first version.

---

# Important Design Principle

Keep the application modular.

In particular, separate:

### 1. CSV ingestion

Responsible for reading the DraftKings player pool.

### 2. Player data

A normalized internal player representation containing things such as:

* Name
* Position
* Team
* Opponent
* Salary
* Projection
* Floor
* Ceiling
* Injury status
* Other statistics

### 3. Projection engine

Responsible for determining expected fantasy production.

### 4. Optimization engine

Responsible for finding legal lineups under:

* salary cap
* roster requirements
* positional eligibility

### 5. Simulation engine

Responsible for Monte Carlo outcome modeling.

### 6. Streamlit UI

Responsible only for presentation and user interaction.

This separation will make it much easier to replace or improve the projection/data source later.

---

# First Version / MVP

Do **not** attempt to build everything at once.

Recommended MVP:

## Step 1

Create Streamlit application.

## Step 2

Allow user to upload DraftKings player-pool CSV.

## Step 3

Inspect and normalize the CSV columns.

Important: **Do not assume the CSV column names until the actual CSV has been inspected.**

## Step 4

Display the imported player pool in the UI.

Include at minimum:

* Player
* Position
* Team
* Salary

## Step 5

Implement the roster constraints:

```text
QB = 1
RB = 2
WR = 3
TE = 1
FLEX = RB/WR/TE
DST = 1
Salary <= $50,000
```

## Step 6

Add a basic projection field.

Initially this could be manually supplied or based on an available data source.

## Step 7

Build a basic optimizer that maximizes projected fantasy points.

## Step 8

Display the recommended lineup with:

* Player
* Position
* Salary
* Projection
* Value
* Total salary
* Projected total

Once this works reliably, add the more sophisticated features.

---

# Important DraftKings Consideration

DraftKings does not appear to offer a simple, stable, official public fantasy-football API intended for this use.

There are unofficial libraries/endpoints available on the internet, but these may change without notice.

Therefore:

**Do not make the application dependent on scraping DraftKings.**

The user's exported CSV should be treated as the authoritative weekly player pool.

---

# Long-Term Vision

Eventually the application could become something more sophisticated than a simple lineup optimizer.

Potential workflow:

```text
DraftKings CSV
      ↓
Player Pool
      ↓
NFL / Player Data
      ↓
Projection Model
      ↓
Floor / Ceiling Model
      ↓
Monte Carlo Simulation
      ↓
Lineup Optimizer
      ↓
League-Specific Analysis
      ↓
Recommended Lineups
```

Possible final output could include several recommendations:

### Lineup A — Highest Projection

The lineup with the highest expected score.

### Lineup B — High Floor

The lineup with the strongest downside protection.

### Lineup C — High Ceiling

The lineup with the greatest upside.

### Lineup D — Balanced

A compromise between projection, floor, and ceiling.

### Lineup E — Contrarian

A lineup designed to have a better chance of separating from opponents.

---

# Immediate Next Step

The immediate task should be to obtain and inspect **one actual weekly DraftKings player-pool CSV**.

Once the CSV is available, determine:

1. Exact column names.
2. How players are identified.
3. Position representation.
4. Salary representation.
5. Team/opponent fields.
6. Any existing projection/statistical fields.
7. Whether FLEX eligibility can be derived from position.
8. Whether DST appears as a normal position or uses a special representation.

**Do not write the CSV parser based on assumptions. Inspect the actual file first.**

After that, build the MVP optimizer around the actual data structure.
