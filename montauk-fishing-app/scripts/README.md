# CoastWatch Ingestion Scripts

These scripts fetch NOAA CoastWatch ERDDAP subsets by date and bounding box, save the raw CSV locally, and write processed JSON outputs for backend consumption.

## Configure ERDDAP Dataset IDs

Edit [`scripts/coastwatch_ingest/config.py`](/C:/Users/miles/OneDrive/Documents/Playground/montauk-fishing-app/scripts/coastwatch_ingest/config.py) and set:

- `ERDDAP_BASE_URL`
- `SST_PRODUCT.dataset_id`
- `CHLOROPHYLL_PRODUCT.dataset_id`
- `variable_name` / `value_column_candidates` if the CSV headers differ from the defaults

The file includes comments showing where the NOAA CoastWatch ERDDAP dataset IDs and request URL pattern should be configured.

## Examples

```powershell
python scripts/fetch_coastwatch_sst.py --date 2026-06-18 --min-lat 39.8 --max-lat 41.4 --min-lon -72.4 --max-lon -69.8
python scripts/fetch_coastwatch_chlorophyll.py --date 2026-06-18 --min-lat 39.8 --max-lat 41.4 --min-lon -72.4 --max-lon -69.8
```

## Output Locations

- Raw CSV: `data/raw/coastwatch/<product>/<date>/...csv`
- Processed JSON: `data/processed/coastwatch/<product>/<date>/...json`

The processed JSON includes metadata, the source URL, query bounds, summary stats, and a flattened `grid` array with `latitude`, `longitude`, and `value`.
