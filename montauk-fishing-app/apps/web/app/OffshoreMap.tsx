"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import styles from "./page.module.css";

type Zone = {
  id: string;
  name: string;
  species: string[];
  distance_nm: number;
  center: { lat: number; lng: number };
  scored_for_species: string;
  scored_for_date: string;
  score: number;
  sea_surface_temp_f: number;
  temp_gradient_f_per_nm: number;
  summary: string;
};

type SstMapFeature = {
  type: "Feature";
  geometry: {
    type: "Point";
    coordinates: [number, number];
  };
  properties: {
    sea_surface_temp_f: number;
  };
};

type SstMapResponse = {
  metadata: {
    date: string;
    bbox: [number, number, number, number];
    source: "live" | "processed" | "mock_fallback" | "unavailable" | string;
    units: "fahrenheit";
    point_count: number;
    temp_range_f: [number, number] | null;
  };
  data: {
    type: "FeatureCollection";
    features: SstMapFeature[];
  };
};

type OffshoreMapProps = {
  zones: Zone[];
  sstMapData: SstMapResponse | null;
  isZonesLoading: boolean;
  isSstMapLoading: boolean;
  zonesError: string | null;
  sstMapError: string | null;
};

type MapLibreRuntime = typeof import("maplibre-gl");

const DEFAULT_CENTER: [number, number] = [-71.9442, 41.0359];
const DEFAULT_BOUNDS: [[number, number], [number, number]] = [
  [-72.45, 39.85],
  [-69.75, 41.45],
];

const BASEMAP_STYLE: {
  version: 8;
  sources: {
    "carto-dark": {
      type: "raster";
      tiles: string[];
      tileSize: number;
      attribution: string;
    };
  };
  layers: Array<{
    id: string;
    type: "raster";
    source: string;
  }>;
} = {
  version: 8,
  sources: {
    "carto-dark": {
      type: "raster",
      tiles: ["https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; CARTO',
    },
  },
  layers: [
    {
      id: "carto-dark",
      type: "raster",
      source: "carto-dark",
    },
  ],
};

function buildZoneFeatureCollection(zones: Zone[]) {
  return {
    type: "FeatureCollection" as const,
    features: zones.map((zone) => ({
      type: "Feature" as const,
      geometry: {
        type: "Point" as const,
        coordinates: [zone.center.lng, zone.center.lat],
      },
      properties: {
        id: zone.id,
        name: zone.name,
        summary: zone.summary,
        score: zone.score,
        distance_nm: zone.distance_nm,
        sea_surface_temp_f: zone.sea_surface_temp_f,
        scored_for_species: zone.scored_for_species,
      },
    })),
  };
}

function getSourceLabel(source: string | null): string {
  if (source === "live") {
    return "Live SST";
  }
  if (source === "processed") {
    return "Processed SST";
  }
  if (source === "mock_fallback") {
    return "Mock SST fallback";
  }
  if (source === "unavailable") {
    return "SST unavailable";
  }
  return "SST source unknown";
}

export default function OffshoreMap({
  zones,
  sstMapData,
  isZonesLoading,
  isSstMapLoading,
  zonesError,
  sstMapError,
}: OffshoreMapProps) {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<any>(null);
  const popupRef = useRef<any>(null);
  const [sstOpacity, setSstOpacity] = useState(0.62);
  const [mapReady, setMapReady] = useState(false);
  const [mapRuntimeError, setMapRuntimeError] = useState<string | null>(null);

  const zoneGeoJson = useMemo(() => buildZoneFeatureCollection(zones), [zones]);
  const sstGeoJson = useMemo(
    () =>
      sstMapData?.data ?? {
        type: "FeatureCollection" as const,
        features: [],
      },
    [sstMapData],
  );

  useEffect(() => {
    let disposed = false;

    async function initializeMap() {
      if (!mapContainerRef.current || mapRef.current) {
        return;
      }

      let maplibre: MapLibreRuntime;
      try {
        maplibre = await import("maplibre-gl");
      } catch (error: unknown) {
        setMapRuntimeError(error instanceof Error ? error.message : "Failed to load MapLibre.");
        return;
      }
      if (disposed || !mapContainerRef.current) {
        return;
      }

      const map = new maplibre.Map({
        container: mapContainerRef.current,
        style: BASEMAP_STYLE,
        center: DEFAULT_CENTER,
      zoom: 6.2,
      minZoom: 4,
      maxZoom: 12,
      attributionControl: {},
    });

      map.addControl(new maplibre.NavigationControl(), "top-right");
      map.on("load", () => {
        setMapReady(true);
        map.resize();
        map.fitBounds(DEFAULT_BOUNDS, { padding: 48, duration: 0 });

        map.addSource("sst-grid", {
          type: "geojson",
          data: {
            type: "FeatureCollection",
            features: [],
          },
        });
        map.addLayer({
          id: "sst-grid-circles",
          type: "circle",
          source: "sst-grid",
          paint: {
            "circle-radius": [
              "interpolate",
              ["linear"],
              ["zoom"],
              5,
              3,
              7,
              7,
              9,
              12,
            ],
            "circle-color": [
              "interpolate",
              ["linear"],
              ["get", "sea_surface_temp_f"],
              54,
              "#2444a6",
              60,
              "#2f82c7",
              65,
              "#2ec4b6",
              69,
              "#a8e063",
              72,
              "#ffd166",
              76,
              "#f77f00",
              80,
              "#d62828",
            ],
            "circle-opacity": sstOpacity,
            "circle-stroke-color": "rgba(7, 18, 29, 0.45)",
            "circle-stroke-width": 0.6,
          },
        });

        map.addSource("ranked-zones", {
          type: "geojson",
          data: {
            type: "FeatureCollection",
            features: [],
          },
        });
        map.addLayer({
          id: "ranked-zones-circles",
          type: "circle",
          source: "ranked-zones",
          paint: {
            "circle-radius": [
              "interpolate",
              ["linear"],
              ["get", "score"],
              50,
              7,
              100,
              13,
            ],
            "circle-color": "#f8fbff",
            "circle-stroke-color": "#66f0c9",
            "circle-stroke-width": 2,
            "circle-opacity": 0.95,
          },
        });
        map.addLayer({
          id: "ranked-zones-labels",
          type: "symbol",
          source: "ranked-zones",
          layout: {
            "text-field": ["get", "name"],
            "text-size": 11,
            "text-offset": [0, 1.6],
            "text-anchor": "top",
          },
          paint: {
            "text-color": "#f8fbff",
            "text-halo-color": "rgba(4, 13, 20, 0.86)",
            "text-halo-width": 1.2,
          },
        });

        popupRef.current = new maplibre.Popup({
          closeButton: false,
          closeOnClick: false,
          offset: 12,
        });

        map.on("mousemove", "sst-grid-circles", (event: any) => {
          const feature = event.features?.[0] as SstMapFeature | undefined;
          if (!feature || !popupRef.current) {
            return;
          }
          map.getCanvas().style.cursor = "crosshair";
          popupRef.current
            .setLngLat(feature.geometry.coordinates)
            .setHTML(`<strong>${feature.properties.sea_surface_temp_f.toFixed(1)} F</strong><br/>Surface temp`)
            .addTo(map);
        });

        map.on("mouseleave", "sst-grid-circles", () => {
          map.getCanvas().style.cursor = "";
          popupRef.current?.remove();
        });

        map.on("mousemove", "ranked-zones-circles", (event: any) => {
          const feature = event.features?.[0] as
            | {
                geometry: { coordinates: [number, number] };
                properties: {
                  name: string;
                  score: number;
                  summary: string;
                  sea_surface_temp_f: number;
                };
              }
            | undefined;
          if (!feature || !popupRef.current) {
            return;
          }
          map.getCanvas().style.cursor = "pointer";
          popupRef.current
            .setLngLat(feature.geometry.coordinates)
            .setHTML(
              `<strong>${feature.properties.name}</strong><br/>Score ${feature.properties.score.toFixed(1)}<br/>SST ${feature.properties.sea_surface_temp_f.toFixed(1)} F<br/>${feature.properties.summary}`,
            )
            .addTo(map);
        });

        map.on("mouseleave", "ranked-zones-circles", () => {
          map.getCanvas().style.cursor = "";
          popupRef.current?.remove();
        });
      });

      mapRef.current = map;
    }

    initializeMap();

    return () => {
      disposed = true;
      popupRef.current?.remove();
      mapRef.current?.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) {
      return;
    }
    const source = map.getSource("sst-grid");
    if (source) {
      source.setData(sstGeoJson);
    }
  }, [mapReady, sstGeoJson]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) {
      return;
    }
    const source = map.getSource("ranked-zones");
    if (source) {
      source.setData(zoneGeoJson);
    }

    if (zones.length > 0) {
      const longitudes = zones.map((zone) => zone.center.lng);
      const latitudes = zones.map((zone) => zone.center.lat);
      map.fitBounds(
        [
          [Math.min(...longitudes), Math.min(...latitudes)],
          [Math.max(...longitudes), Math.max(...latitudes)],
        ],
        { padding: 72, duration: 0, maxZoom: 7.4 },
      );
      return;
    }

    if (sstMapData?.metadata.bbox) {
      const [minLng, minLat, maxLng, maxLat] = sstMapData.metadata.bbox;
      map.fitBounds(
        [
          [minLng, minLat],
          [maxLng, maxLat],
        ],
        { padding: 56, duration: 0, maxZoom: 7.2 },
      );
    }
  }, [mapReady, zoneGeoJson, zones, sstMapData]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) {
      return;
    }

    const handleResize = () => map.resize();
    handleResize();
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
    };
  }, [mapReady]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.getLayer("sst-grid-circles")) {
      return;
    }
    map.setPaintProperty("sst-grid-circles", "circle-opacity", sstOpacity);
  }, [sstOpacity]);

  const overlayUnavailable =
    Boolean(sstMapError) || Boolean(mapRuntimeError) || sstMapData?.metadata.source === "unavailable";

  return (
    <>
      <div className={styles.mapCanvas} ref={mapContainerRef} />

      <div className={styles.hud}>
        <div className={styles.brand}>
          <p className={styles.eyebrow}>Montauk Offshore Intelligence</p>
          <h1 className={styles.title}>Read the water before the run.</h1>
          <p className={styles.subtitle}>
            A real Montauk offshore map with ranked-zone markers and a backend-driven SST layer.
          </p>
        </div>

        <div className={styles.legend}>
          <div className={styles.legendHeader}>
            <p className={styles.legendTitle}>SST Overlay</p>
            <span className={styles.sourceBadge}>{getSourceLabel(sstMapData?.metadata.source ?? null)}</span>
          </div>
          <div className={styles.temperatureRamp} />
          <div className={styles.temperatureScale}>
            <span>54 F</span>
            <span>66 F</span>
            <span>80 F</span>
          </div>
          <label className={styles.opacityControl}>
            <span>Overlay opacity</span>
            <input
              max="0.95"
              min="0.15"
              onChange={(event) => setSstOpacity(Number(event.target.value))}
              step="0.05"
              type="range"
              value={sstOpacity}
            />
          </label>
          <div className={styles.legendList}>
            <div className={styles.legendItem}>
              <span className={styles.legendSwatch} style={{ background: "#66f0c9" }} />
              Ranked zone marker
            </div>
            <div className={styles.legendItem}>
              <span className={styles.legendSwatchWarm} />
              Backend SST point grid
            </div>
          </div>
          {sstMapData?.metadata.temp_range_f && (
            <p className={styles.controlHint}>
              Visible SST range {sstMapData.metadata.temp_range_f[0].toFixed(1)}-
              {sstMapData.metadata.temp_range_f[1].toFixed(1)} F across {sstMapData.metadata.point_count} points.
            </p>
          )}
        </div>
      </div>

      <div className={styles.mapFeedback}>
        {isZonesLoading && <p className={styles.loadingBanner}>Refreshing zone rankings...</p>}
        {isSstMapLoading && <p className={styles.loadingBanner}>Refreshing SST overlay...</p>}
        {zonesError && <p className={styles.errorBanner}>{zonesError}</p>}
        {mapRuntimeError && <p className={styles.errorBanner}>{mapRuntimeError}</p>}
        {overlayUnavailable && (
          <p className={styles.errorBanner}>
            SST overlay unavailable. Zone markers remain active while the backend falls back or recovers.
          </p>
        )}
      </div>
    </>
  );
}
