# eAutoViz AI — Full Product Demo Script (one dataset: Palmer Penguins)

**File to upload:** `penguins-raw.csv`. It has 344 penguins. 11 rows have empty cells: 2 have no measurements, and 9 have no sex recorded.
**Target length:** about 8 minutes. For the 3-minute pitch slot, keep only the scenes marked ★.
**Before recording:**

- Log out.
- Clear old dashboards, or use a fresh account.
- Set browser zoom to 125%.
- Have a private/incognito window ready for the share step.

Every step below was checked against the app's labels and against the real analysis engine. Chart results and numbers are what the engine produces on this file. The AI's wording will vary.

---



## Scene 1 — Sign in ★ (0:00–0:20)


| Do                                                                                        | Say                                                                                                                       |
| ----------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| Open `autoviz.duckdns.org`. You land on the sign-in page.                                 | "This is AutoViz AI. You ask questions about a spreadsheet in plain language, and you get charts you can actually check." |
| Type email and password, click **Sign in**. (Google and GitHub sign-in are also offered.) | "I'll sign in. Every dataset, chart and dashboard belongs to this account only."                                          |




## Scene 2 — Upload the file ★ (0:20–0:50)


| Do                                                                                | Say                                                                                                   |
| --------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| On the empty canvas click **Add data file** (or drag `penguins-raw.csv` onto it). | "We accept CSV, Excel, Parquet and JSON. I'll upload a public dataset: 344 penguins from Antarctica." |
| In **Name this dataset**, type `Penguins raw`, click **Upload**.                  | "The file is stored on our server. It is never sent to the AI."                                       |
| Point at the card: *344 rows × 7 columns*.                                        | "Seven columns: species, island, bill length and depth, flipper length, body mass and sex."           |




## Scene 3 — Look at and edit the dataset (0:50–1:40)

Do this **before** asking for any charts. Saving an edit creates a cleaned copy of the dataset and starts a fresh dashboard.


| Do                                                                                   | Say                                                                                                                              |
| ------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------- |
| Click **Open Data** (or sidebar **Edit Dataset**). The spreadsheet opens.            | "Before asking anything, I can look at the data and fix it myself, like a normal spreadsheet."                                   |
| Point at row 4 (*Adelie, Torgersen*, every measurement empty).                       | "This penguin has no measurements at all, and a few others have no sex recorded. That would add a 'blank' group to some charts." |
| Click **Drop Empty**.                                                                | "Drop Empty removes every row with a missing value. 344 rows become 333."                                                        |
| *(Optional)* Click a cell, change it, then **Discard** to show edits are reversible. | "Every edit stays local until I save."                                                                                           |
| Click **Save**. If asked for a name, type `Penguins clean` and click **Upload**.     | "Saving keeps the original file untouched and creates a cleaned copy. From here we use this clean version."                      |




## Scene 4 — The privacy notice and the first question ★ (1:40–2:20)


| Do                                                                                                        | Say                                                                                                                                                                                                          |
| --------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Open **AI Chat**. The notice appears.                                                                     | "Before the first question, AutoViz tells you exactly what goes to the AI: the question, the column names and types, and a short profile. Full rows, the file and passwords are **not** sent."               |
| Click **I understand — continue**.                                                                        |                                                                                                                                                                                                              |
| Type **Which penguin species has the deepest bills?** and press Enter. (Cut the 10–15 s wait in editing.) | "A request takes about twelve seconds, almost all of it the AI planning."                                                                                                                                    |
| Chart appears: a bar chart of the three species. Read the summary under it in chat.                       | "The AI didn't calculate these numbers. It wrote a plan; our code ran it as a database query and drew the chart. And every number in this summary was checked against the query result before it was shown." |
| Click the **ⓘ** icon (**About this chart**).                                                              | "And here's a plain-English description of what the chart shows, written by code, not the AI."                                                                                                               |




## Scene 5 — Open the plan and edit it ★ (2:20–3:40)


| Do                                                                                                    | Say                                                                                                                                                                             |
| ----------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Type **Average body mass by species** and send. A 3-bar chart appears (Gentoo about 5,090 g).         | "Let's take a simpler question."                                                                                                                                                |
| Click the **{ }** icon (**View / edit analysis plan**). The **Plan** panel opens.                     | "This is everything the AI decided: which column to group by, what to average, which chart. No code, no numbers. Anyone can read it."                                           |
| In the JSON change `"group_by": ["species"]` to `"group_by": ["species", "sex"]`. Click **Run plan**. | "Now I'll change the plan myself. I add sex to the grouping and press Run plan."                                                                                                |
| Chart becomes a grouped bar (6 bars). Point at the line under it: *re-run from edited plan*.          | "The chart rebuilt instantly, and the AI was **not** called. One field changed, and the chart changed with it. If the AI ever gets something wrong, you can fix it right here." |
| Add a filter: `"filters": [{"column": "island", "op": "eq", "value": "Biscoe"}]`, **Run plan**.       | "Let's only look at Biscoe Island. Chinstrap penguins disappear, because none live there."                                                                                      |
| Change `"species"` in `group_by` to `"colour"`, **Run plan**. A red error appears.                    | "And if a plan names a column that doesn't exist, it's rejected before anything runs. No invented columns."                                                                     |
| Click **Reset**.                                                                                      | "Reset puts the plan back."                                                                                                                                                     |




## Scene 6 — It asks when unclear, and declines what it can't do ★ (3:40–4:30)


| Do                                                                                                                                                         | Say                                                                                        |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| Type **Which species is best?**                                                                                                                            | "Now a vague question. 'Best' at what?"                                                    |
| Chat replies: *"Which measure should rank them? 'best' isn't a column."* with buttons (average bill length, body mass, bill depth, flipper length, count). | "Instead of guessing, AutoViz asks. And every option is a real column in this dataset."    |
| Click **Average flipper length mm**. Chart appears.                                                                                                        | "I pick one, and now it answers the question I actually meant."                            |
| Type **Predict how many penguins there will be next year.**                                                                                                | "What if I ask for something it can't do?"                                                 |
| Reply: *"AutoViz describes data that already exists — it cannot forecast or predict."* Click **Nothing — cancel this request**.                            | "It says so honestly and offers what it can do instead, rather than making up a forecast." |




## Scene 7 — More chart types and refining a chart (4:30–5:40)


| Do                                                                                              | Say                                                                                               |
| ----------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| Type **Is flipper length related to body mass? Colour by species.**                             | "A relationship question gives a scatter plot."                                                   |
| Scatter appears in three clusters. Drag across some points.                                     | "I can brush to select points. The others fade out."                                              |
| Type **How many penguins live on each island?** A donut appears.                                | "A part-to-whole question gives a donut."                                                         |
| Click the **@** on the donut (**Ask the chat about this chart**), type **make it a bar chart**. | "I can point at one chart and change it in words. It updates in place: same position, same size." |
| Sidebar **Setup**, pick **Histogram**, type **bill length**, send.                              | "Or I can pick the chart type myself. Here's the distribution of bill length."                    |




## Scene 8 — Style the chart (5:40–6:20)


| Do                                                                                                                                      | Say                                                                                          |
| --------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| On the bar chart click the palette icon (**Style options**). In **Title** type `Average body mass of penguins`. Change a series colour. | "Styling is instant. Titles, axis labels, fonts and colours, with no AI call."               |
| Click the wand icon (**Change how this chart looks**), type **Make the bars orange and remove the legend**, **Apply**.                  | "Or I describe the look I want. The AI only gets to change appearance here, never the data." |




## Scene 9 — Build the dashboard (6:20–7:00)


| Do                                                                                                        | Say                                            |
| --------------------------------------------------------------------------------------------------------- | ---------------------------------------------- |
| Drag charts by their headers into a tidy layout; resize one from the bottom-right corner.                 | "All charts live on one canvas I can arrange." |
| Click the trash icon on one chart, then **Undo** in the notice.                                           | "Delete by mistake? Undo."                     |
| Click the board title (**Rename this dashboard**), name it `Penguin study`, **Save**. Point at **Saved**. | "The dashboard saves automatically."           |




## Scene 10 — Share (7:00–7:25)


| Do                                                                          | Say                                                                                           |
| --------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| Click **Share ▾**, turn on **Public access**, click **Copy Link**.          | "To share, I switch on public access and copy the link."                                      |
| Paste into the private window. The read-only dashboard opens without login. | "Anyone with the link sees the dashboard, read-only. They can't edit it or see the raw file." |




## Scene 11 — Export ★ (7:25–7:50)


| Do                                                                                            | Say                                                                               |
| --------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| Click **Export ▾** → **PNG image**. Then **Export ▾** → **PDF document**. Show the downloads. | "Finally, export. The whole dashboard as one image or a PDF, ready for a report." |
| *(Optional)* On one chart open the **⋯** menu → **Save as SVG**.                              | "Single charts can be saved too, as SVG or PNG."                                  |




## Scene 12 — Close (7:50–8:10)


| Do                                                                                                                                 | Say                                                                                                             |
| ---------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| *(Optional)* **Settings** → **Connections**: show the page only. **Do not generate a link on camera**: it is a secret, shown once. | "AutoViz can also be used from other AI tools, like Claude, through MCP."                                       |
| Click **Sign out**.                                                                                                                | "So: the AI plans, our code calculates. Every chart can be checked, and your raw data never goes to the model." |


---



## Backup lines and recovery

- **If the AI's chart differs from the script** (e.g. a different chart type), open the plan anyway: "Whatever it chose, here is the plan that explains it."
- **If a request fails**, click **Try again** in the chat.
- **Security add-on for Gimsara's part** (Scene 5 panel): set the Biscoe filter value to `'; DROP TABLE users; --` and press **Run plan**. The engine rejects it: *"value resembles code and is rejected."* Values are always passed as parameters, never pasted into SQL.



## Numbers you can quote (from this file, cleaned)

- 333 penguins after cleaning (344 raw).
- Average body mass: Adelie about 3,706 g, Chinstrap about 3,733 g, Gentoo about 5,092 g.
- Penguins per island: Biscoe 163, Dream 123, Torgersen 47.

