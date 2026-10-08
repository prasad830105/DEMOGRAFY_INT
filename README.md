# Neighbourhood Livability Index demo

This is a sample-data Streamlit prototype comparing amenity density in two suburbs. It does not make external API calls yet. See [KPI-card.md](KPI-card.md) for the proposed metric definition, place-type mapping, calculation, and limitations.

## Run locally (Windows setup used for this demo)

Python 3.14 and the required packages are installed on the current machine. In PowerShell, run:

```powershell
$env:STREAMLIT_CONFIG_DIR = (Join-Path (Get-Location) '.streamlit')
& "$env:LOCALAPPDATA/Programs/Python/Python314/python.exe" -m streamlit run app.py
```

For another machine, create a virtual environment with its installed Python and install packages with `python -m pip install -r requirements.txt`, then run `python -m streamlit run app.py`.

The demo uses in-file fixtures for Parramatta, Chatswood, and Newtown. Google Places, Supabase, a GitHub remote, and Google Cloud project still need to be configured before this becomes a live pipeline. Keep credentials in `.env` or Streamlit secrets; these are excluded by `.gitignore`.
