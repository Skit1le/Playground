from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = PROJECT_ROOT / "data"
RAW_ROOT = DATA_ROOT / "raw" / "coastwatch"
PROCESSED_ROOT = DATA_ROOT / "processed" / "coastwatch"


@dataclass(frozen=True)
class ProductConfig:
    name: str
    variable_name: str
    value_column_candidates: tuple[str, ...]
    raw_subdir: str
    processed_subdir: str
    dataset_id: str
    base_url: str

    @property
    def raw_root(self) -> Path:
        return RAW_ROOT / self.raw_subdir

    @property
    def processed_root(self) -> Path:
        return PROCESSED_ROOT / self.processed_subdir


# Configure CoastWatch ERDDAP dataset IDs and base URL here.
# Replace the placeholder dataset IDs below with the specific NOAA CoastWatch
# ERDDAP griddap dataset IDs you want to target for SST and chlorophyll.
# If the dataset exposes a different data variable column name in CSV output,
# update `variable_name` and `value_column_candidates` as well.
# Official NOAA CoastWatch examples:
# - SST example dataset ID: `noaacwBLENDEDsstDaily`
# - Chlorophyll example dataset IDs vary by coverage/product, for example
#   `noaacwNPPVIIRSchlaWeekly` or regional daily products such as
#   `noaacwNPPVIIRSSCIchlaSectorVZDaily`
# Example URL pattern:
# https://coastwatch.pfeg.noaa.gov/erddap/griddap/<DATASET_ID>.csv?...query...
ERDDAP_BASE_URL = "https://coastwatch.pfeg.noaa.gov/erddap/griddap"

SST_PRODUCT = ProductConfig(
    name="sst",
    variable_name="sea_surface_temperature",
    value_column_candidates=("sea_surface_temperature", "sst", "analysed_sst", "temperature"),
    raw_subdir="sst",
    processed_subdir="sst",
    dataset_id="CONFIGURE_NOAA_COASTWATCH_SST_DATASET_ID",
    base_url=ERDDAP_BASE_URL,
)

CHLOROPHYLL_PRODUCT = ProductConfig(
    name="chlorophyll",
    variable_name="chlorophyll",
    value_column_candidates=("chlorophyll", "chlor_a", "chlorophyll_concentration"),
    raw_subdir="chlorophyll",
    processed_subdir="chlorophyll",
    dataset_id="CONFIGURE_NOAA_COASTWATCH_CHL_DATASET_ID",
    base_url=ERDDAP_BASE_URL,
)
