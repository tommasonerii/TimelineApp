# TimelineApp

TimelineApp is a desktop viewer for visualising personal timelines. It is built with PyQt6 and provides a modern, scrollable interface that combines a rich event timeline with a finance dashboard backed by Yahoo! Finance data.

## Features

- **CSV ingestion:** Import timelines collected from spreadsheet exports. Each row can contain multiple structured events extracted with regular expressions.
- **Per-person filtering:** Quickly switch between people to review only their milestones.
- **Canvas-based timeline:** Events are rendered on a custom `QGraphicsView` with category-aware colours, optional icons, smart label placement, and "today" markers.
- **Finance overlay:** A companion chart retrieves global market indices via `yfinance`, normalises them to the first event date, and shows dashed previews for future milestones.
- **Polished UI:** Rounded chips, modern combo boxes, embedded Lato font files, and Matplotlib integration create a cohesive desktop experience.

## Requirements

- Python 3.10 or later.
- System packages required by Qt (on Linux install `qt6-base-dev` or the equivalent).
- The Python dependencies listed in `requirements.txt` (`pip install -r requirements.txt`).

> **Note:** The final line in `requirements.txt` should be `yfinance`. If you notice it glued to the shell prompt when copying from a terminal, retype it to avoid installation issues.

## Getting started

1. Create and activate a virtual environment (recommended).
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Launch the application:
   ```bash
   python app.py
   ```

The main window opens with controls to load a CSV file and filter by person. Once a person is selected, the timeline canvas and finance chart update automatically.

## CSV format

TimelineApp expects a UTF-8 CSV file with the following columns (case-insensitive):

| Column           | Description                                                      |
| ---------------- | ---------------------------------------------------------------- |
| `Submission Date`| Original submission timestamp (not directly used in rendering).  |
| `Nome`           | The person associated with the row of events.                    |
| `Eventi`         | One or more events encoded as text snippets.                     |

Each `Eventi` cell should include comma-separated clauses such as:

```
Titolo: Laurea magistrale, Categoria: studio, Data: 2020-07-14
Titolo: Assunzione, Categoria: lavoro, Data: 08/09/2021
```

Dates support `YYYY-MM-DD`, `DD/MM/YYYY`, and `MM/DD/YYYY` (with automatic inference when ambiguous). Invalid dates are skipped during import.

## Finance data

The finance panel downloads Adjusted Close prices for a handful of global indices:

- S&P 500 (`^GSPC`)
- Euro Stoxx 50 (`^STOXX50E`)
- FTSE 100 (`^FTSE`)
- Nikkei 225 (`^N225`)
- Hang Seng (`^HSI`)

The series are normalised to 0% on the first event date. Points after the current day are rendered with dashed lines to visually separate future events.

To change the tracked indices, pass a custom dictionary to `FinanceChart(indexes=...)` when constructing the widget.

## Fonts

The UI tries to load the Lato font family from `ui/fonts`. If the files are missing, it gracefully falls back to system fonts. When packaging with PyInstaller, the lookup also covers the `_MEIPASS` extraction directory.

## Development notes

- The codebase is split between `core/` (data parsing, models) and `ui/` (widgets, painting, and styling).
- `TimelineCanvas` lives under `ui/timeline_canvas.py` and contains the rendering logic for the horizontal timeline.
- `FinanceChart` lives under `ui/finance_chart.py` and wraps a Matplotlib canvas inside a Qt widget.
- `MainWindow` (in `ui/main_window.py`) wires everything together and handles CSV selection, filtering, and status updates.

## Packaging

PyInstaller is included in the requirements to support producing a standalone executable:

```bash
pyinstaller --noconfirm --windowed app.py
```

Ensure that the fonts and any icon assets are collected via the spec file or `--add-data` arguments.

## Troubleshooting

- **Qt platform errors:** Install the native Qt runtime for your operating system (`qt6-base` on Debian/Ubuntu, Xcode Command Line Tools on macOS, or the official Qt redistributable on Windows).
- **Empty timeline:** Confirm that the `Eventi` column matches the expected pattern and that the dates parse to valid values.
- **Finance download failures:** The finance chart requires an internet connection and Yahoo! Finance availability; error messages are displayed beneath the chart when downloads fail.

## License

This project does not currently include an explicit license file. Add one if you plan to distribute the application.
