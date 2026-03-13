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
  nearest_strong_break_distance_nm?: number | null;
  summary: string;
  chlorophyll_mg_m3: number;
  nearest_strong_chl_break_distance_nm?: number | null;
  score_explanation?: {
    headline: string;
    summary: string;
    top_reasons?: string[];
    factors?: Array<{
      factor: string;
      label: string;
      raw_value: string;
      score: number;
      weighted_contribution: number;
      reason: string;
    }>;
  };
};

type ChlorophyllBreakMapFeature = {
  type: "Feature";
  geometry: {
    type: "Polygon";
    coordinates: [Array<[number, number]>];
  };
  properties: {
    chlorophyll_mg_m3: number;
    break_intensity_mg_m3_per_nm: number;
  };
};

type SstMapFeature = {
  type: "Feature";
  geometry: {
    type: "Polygon";
    coordinates: [Array<[number, number]>];
  };
  properties: {
    sea_surface_temp_f: number;
    break_intensity_f_per_nm: number;
  };
};

type SstMapResponse = {
  metadata: {
    date: string;
    bbox: [number, number, number, number];
    source: "live" | "processed" | "mock_fallback" | "unavailable" | string;
    units: "fahrenheit";
    point_count: number;
    cell_count: number;
    temp_range_f: [number, number] | null;
    break_intensity_range?: [number, number] | null;
    grid_resolution?: [number, number] | null;
  };
  data: {
    type: "FeatureCollection";
    features: SstMapFeature[];
  };
};

type OffshoreMapProps = {
  zones: Zone[];
  sstMapData: SstMapResponse | null;
  chlorophyllBreakMapData: {
    metadata: {
      source: string;
      break_intensity_range_mg_m3_per_nm?: [number, number] | null;
    };
    data: {
      type: "FeatureCollection";
      features: ChlorophyllBreakMapFeature[];
    };
  } | null;
  isZonesLoading: boolean;
  isSstMapLoading: boolean;
  isChlorophyllBreakMapLoading: boolean;
  zonesError: string | null;
  sstMapError: string | null;
  chlorophyllBreakMapError: string | null;
  selectedZoneId: string | null;
  onZoneSelect: (zoneId: string) => void;
  onViewportBboxChange: (bbox: [number, number, number, number]) => void;
};

type MapLibreRuntime = typeof import("maplibre-gl");

const DEFAULT_CENTER: [number, number] = [-71.94, 41.03];
const DEFAULT_BOUNDS: [[number, number], [number, number]] = [
  [-72.28, 40.62],
  [-71.02, 41.18],
];
const NAUTICAL_TILES = ["https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png"];

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
  chlorophyllBreakMapData,
  isZonesLoading,
  isSstMapLoading,
  isChlorophyllBreakMapLoading,
  zonesError,
  sstMapError,
  chlorophyllBreakMapError,
  selectedZoneId,
  onZoneSelect,
  onViewportBboxChange,
}: OffshoreMapProps) {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<any>(null);
  const popupRef = useRef<any>(null);
  const lastViewportBboxRef = useRef<string>("");
  const [sstOpacity, setSstOpacity] = useState(0.62);
  const [showSstSurface, setShowSstSurface] = useState(true);
  const [showSstGrid, setShowSstGrid] = useState(false);
  const [showTempBreaks, setShowTempBreaks] = useState(true);
  const [showChlorophyllBreaks, setShowChlorophyllBreaks] = useState(true);
  const [showNauticalOverlay, setShowNauticalOverlay] = useState(true);
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
  const chlorophyllBreakGeoJson = useMemo(
    () =>
      chlorophyllBreakMapData?.data ?? {
        type: "FeatureCollection" as const,
        features: [],
      },
    [chlorophyllBreakMapData],
  );

  function emitViewportBbox(map: any) {
    const bounds = map.getBounds();
    const bbox: [number, number, number, number] = [
      Number(bounds.getWest().toFixed(4)),
      Number(bounds.getSouth().toFixed(4)),
      Number(bounds.getEast().toFixed(4)),
      Number(bounds.getNorth().toFixed(4)),
    ];
    const key = bbox.join(",");
    if (lastViewportBboxRef.current === key) {
      return;
    }
    lastViewportBboxRef.current = key;
    onViewportBboxChange(bbox);
  }

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
        emitViewportBbox(map);

        map.addSource("sst-grid", {
          type: "geojson",
          data: {
            type: "FeatureCollection",
            features: [],
          },
        });
        map.addSource("nautical-chart", {
          type: "raster",
          tiles: NAUTICAL_TILES,
          tileSize: 256,
          attribution: '&copy; <a href="https://www.openseamap.org/">OpenSeaMap</a> contributors',
        });
        map.addLayer({
          id: "nautical-chart-layer",
          type: "raster",
          source: "nautical-chart",
          layout: {
            visibility: showNauticalOverlay ? "visible" : "none",
          },
          paint: {
            "raster-opacity": 0.58,
          },
        });
        map.addLayer({
          id: "sst-grid-fill",
          type: "fill",
          source: "sst-grid",
          layout: {
            visibility: "visible",
          },
          paint: {
            "fill-color": [
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
            "fill-antialias": true,
            "fill-opacity": sstOpacity,
          },
        });
        map.addLayer({
          id: "sst-breaks-fill",
          type: "fill",
          source: "sst-grid",
          layout: {
            visibility: "visible",
          },
          paint: {
            "fill-color": [
              "interpolate",
              ["linear"],
              ["get", "break_intensity_f_per_nm"],
              0,
              "rgba(0,0,0,0)",
              0.012,
              "rgba(255,245,200,0.16)",
              0.025,
              "rgba(255,196,96,0.34)",
              0.04,
              "rgba(255,120,54,0.58)",
              0.06,
              "rgba(255,74,74,0.78)",
              0.085,
              "rgba(255,255,255,0.94)",
            ],
            "fill-opacity": 0.82,
          },
        });
        map.addLayer({
          id: "sst-grid-outline",
          type: "line",
          source: "sst-grid",
          layout: {
            visibility: "none",
          },
          paint: {
            "line-color": "rgba(255, 255, 255, 0.16)",
            "line-width": 0.45,
            "line-opacity": 0.22,
          },
        });
        map.addLayer({
          id: "sst-breaks-outline",
          type: "line",
          source: "sst-grid",
          layout: {
            visibility: "none",
          },
          paint: {
            "line-color": [
              "interpolate",
              ["linear"],
              ["get", "break_intensity_f_per_nm"],
              0,
              "rgba(0,0,0,0)",
              0.03,
              "rgba(255,214,122,0.22)",
              0.055,
              "rgba(255,122,69,0.56)",
              0.08,
              "rgba(255,255,255,0.92)",
            ],
            "line-width": [
              "interpolate",
              ["linear"],
              ["get", "break_intensity_f_per_nm"],
              0,
              0,
              0.03,
              0.6,
              0.055,
              1.1,
              0.08,
              1.8,
            ],
            "line-opacity": 0.78,
          },
        });
        map.addSource("chlorophyll-breaks", {
          type: "geojson",
          data: {
            type: "FeatureCollection",
            features: [],
          },
        });
        map.addLayer({
          id: "chlorophyll-breaks-fill",
          type: "fill",
          source: "chlorophyll-breaks",
          layout: {
            visibility: "none",
          },
          paint: {
            "fill-color": [
              "interpolate",
              ["linear"],
              ["get", "break_intensity_mg_m3_per_nm"],
              0,
              "rgba(0,0,0,0)",
              0.006,
              "rgba(83,255,182,0.14)",
              0.012,
              "rgba(112,246,154,0.28)",
              0.02,
              "rgba(188,255,76,0.45)",
              0.03,
              "rgba(244,255,158,0.68)",
            ],
            "fill-opacity": 0.74,
          },
        });
        map.addLayer({
          id: "chlorophyll-breaks-line",
          type: "line",
          source: "chlorophyll-breaks",
          layout: {
            visibility: "none",
          },
          paint: {
            "line-color": [
              "interpolate",
              ["linear"],
              ["get", "break_intensity_mg_m3_per_nm"],
              0,
              "rgba(0,0,0,0)",
              0.01,
              "rgba(123,255,187,0.24)",
              0.02,
              "rgba(198,255,95,0.58)",
              0.03,
              "rgba(246,255,201,0.9)",
            ],
            "line-width": [
              "interpolate",
              ["linear"],
              ["get", "break_intensity_mg_m3_per_nm"],
              0,
              0,
              0.01,
              0.5,
              0.02,
              1.0,
              0.03,
              1.6,
            ],
            "line-opacity": 0.84,
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
            "circle-color": [
              "case",
              ["==", ["get", "id"], ["literal", selectedZoneId ?? ""]],
              "#fff4d8",
              "#f8fbff",
            ],
            "circle-stroke-color": [
              "case",
              ["==", ["get", "id"], ["literal", selectedZoneId ?? ""]],
              "#ffb55f",
              "#66f0c9",
            ],
            "circle-stroke-width": [
              "case",
              ["==", ["get", "id"], ["literal", selectedZoneId ?? ""]],
              3.2,
              2,
            ],
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

        map.on("mousemove", "sst-grid-fill", (event: any) => {
          const feature = event.features?.[0] as SstMapFeature | undefined;
          if (!feature || !popupRef.current) {
            return;
          }
          map.getCanvas().style.cursor = "crosshair";
          popupRef.current
            .setLngLat(event.lngLat)
            .setHTML(
              `<strong>${feature.properties.sea_surface_temp_f.toFixed(1)} F</strong><br/>Break ${feature.properties.break_intensity_f_per_nm.toFixed(3)} F/nm`,
            )
            .addTo(map);
        });

        map.on("mouseleave", "sst-grid-fill", () => {
          map.getCanvas().style.cursor = "";
          popupRef.current?.remove();
        });

        map.on("mousemove", "chlorophyll-breaks-fill", (event: any) => {
          const feature = event.features?.[0] as ChlorophyllBreakMapFeature | undefined;
          if (!feature || !popupRef.current) {
            return;
          }
          map.getCanvas().style.cursor = "crosshair";
          popupRef.current
            .setLngLat(event.lngLat)
            .setHTML(
              `<strong>Chl ${feature.properties.chlorophyll_mg_m3.toFixed(2)} mg/m3</strong><br/>Break ${feature.properties.break_intensity_mg_m3_per_nm.toFixed(3)} mg/m3/nm`,
            )
            .addTo(map);
        });

        map.on("mouseleave", "chlorophyll-breaks-fill", () => {
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

        map.on("click", "ranked-zones-circles", (event: any) => {
          const feature = event.features?.[0] as
            | {
                properties: { id: string; name: string; score: number; summary: string };
                geometry: { coordinates: [number, number] };
              }
            | undefined;
          if (!feature || !popupRef.current) {
            return;
          }
          onZoneSelect(feature.properties.id);
          popupRef.current
            .setLngLat(feature.geometry.coordinates)
            .setHTML(
              `<strong>${feature.properties.name}</strong><br/>Score ${feature.properties.score.toFixed(1)}<br/>${feature.properties.summary}`,
            )
            .addTo(map);
        });

        map.on("moveend", () => {
          emitViewportBbox(map);
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
  }, [onViewportBboxChange]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) {
      return;
    }
    const source = map.getSource("sst-grid");
    if (source) {
      source.setData(sstGeoJson);
      if (process.env.NODE_ENV !== "production") {
        console.info("Mounted SST overlay source", {
          featureCount: sstGeoJson.features.length,
          source: sstMapData?.metadata.source ?? "unknown",
        });
      }
      return;
    }

    if (process.env.NODE_ENV !== "production" && sstGeoJson.features.length > 0) {
      console.warn("SST features were loaded but the sst-grid source is missing.");
    }
  }, [mapReady, sstGeoJson, sstMapData]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) {
      return;
    }
    const source = map.getSource("chlorophyll-breaks");
    if (source) {
      source.setData(chlorophyllBreakGeoJson);
    }
  }, [chlorophyllBreakGeoJson, mapReady]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) {
      return;
    }
    const source = map.getSource("ranked-zones");
    if (source) {
      source.setData(zoneGeoJson);
    }
  }, [mapReady, zoneGeoJson]);

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
    if (!map) {
      return;
    }
    if (map.getLayer("sst-grid-fill")) {
      map.setPaintProperty("sst-grid-fill", "fill-opacity", sstOpacity);
    }
  }, [sstOpacity]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) {
      return;
    }
    if (map.getLayer("sst-grid-fill")) {
      map.setLayoutProperty("sst-grid-fill", "visibility", showSstSurface ? "visible" : "none");
    }
    if (map.getLayer("sst-breaks-fill")) {
      map.setLayoutProperty(
        "sst-breaks-fill",
        "visibility",
        showSstSurface && showTempBreaks ? "visible" : "none",
      );
    }
    if (map.getLayer("sst-grid-outline")) {
      map.setLayoutProperty(
        "sst-grid-outline",
        "visibility",
        showSstSurface && showSstGrid ? "visible" : "none",
      );
    }
    if (map.getLayer("sst-breaks-outline")) {
      map.setLayoutProperty(
        "sst-breaks-outline",
        "visibility",
        showSstSurface && showTempBreaks ? "visible" : "none",
      );
    }
    if (map.getLayer("chlorophyll-breaks-fill")) {
      map.setLayoutProperty(
        "chlorophyll-breaks-fill",
        "visibility",
        showChlorophyllBreaks ? "visible" : "none",
      );
    }
    if (map.getLayer("chlorophyll-breaks-line")) {
      map.setLayoutProperty(
        "chlorophyll-breaks-line",
        "visibility",
        showChlorophyllBreaks ? "visible" : "none",
      );
    }
  }, [showChlorophyllBreaks, showSstGrid, showSstSurface, showTempBreaks]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.getLayer("nautical-chart-layer")) {
      return;
    }
    map.setLayoutProperty(
      "nautical-chart-layer",
      "visibility",
      showNauticalOverlay ? "visible" : "none",
    );
  }, [showNauticalOverlay]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.getLayer("ranked-zones-circles")) {
      return;
    }
    map.setPaintProperty("ranked-zones-circles", "circle-color", [
      "case",
      ["==", ["get", "id"], ["literal", selectedZoneId ?? ""]],
      "#fff4d8",
      "#f8fbff",
    ]);
    map.setPaintProperty("ranked-zones-circles", "circle-stroke-color", [
      "case",
      ["==", ["get", "id"], ["literal", selectedZoneId ?? ""]],
      "#ffb55f",
      "#66f0c9",
    ]);
    map.setPaintProperty("ranked-zones-circles", "circle-stroke-width", [
      "case",
      ["==", ["get", "id"], ["literal", selectedZoneId ?? ""]],
      3.2,
      2,
    ]);
  }, [selectedZoneId]);

  const overlayUnavailable =
    Boolean(sstMapError) || Boolean(mapRuntimeError) || sstMapData?.metadata.source === "unavailable";
  const hasOverlayCells = (sstMapData?.data.features.length ?? 0) > 0;

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
            <span>Show SST surface</span>
            <input
              checked={showSstSurface}
              onChange={(event) => setShowSstSurface(event.target.checked)}
              type="checkbox"
            />
          </label>
          <label className={styles.opacityControl}>
            <span>Show SST cell boundaries</span>
            <input
              checked={showSstGrid}
              disabled={!showSstSurface}
              onChange={(event) => setShowSstGrid(event.target.checked)}
              type="checkbox"
            />
          </label>
          <label className={styles.opacityControl}>
            <span>Show Temp Breaks</span>
            <input
              checked={showTempBreaks}
              disabled={!showSstSurface}
              onChange={(event) => setShowTempBreaks(event.target.checked)}
              type="checkbox"
            />
          </label>
          <label className={styles.opacityControl}>
            <span>Show Chlorophyll Breaks</span>
            <input
              checked={showChlorophyllBreaks}
              onChange={(event) => setShowChlorophyllBreaks(event.target.checked)}
              type="checkbox"
            />
          </label>
          <label className={styles.opacityControl}>
            <span>Overlay opacity</span>
            <input
              disabled={!showSstSurface}
              max="0.95"
              min="0.15"
              onChange={(event) => setSstOpacity(Number(event.target.value))}
              step="0.05"
              type="range"
              value={sstOpacity}
            />
          </label>
          <label className={styles.opacityControl}>
            <span>Nautical chart overlay</span>
            <input
              checked={showNauticalOverlay}
              onChange={(event) => setShowNauticalOverlay(event.target.checked)}
              type="checkbox"
            />
          </label>
          <div className={styles.legendList}>
            <div className={styles.legendItem}>
              <span className={styles.legendSwatch} style={{ background: "#66f0c9" }} />
              Ranked zone marker
            </div>
            <div className={styles.legendItem}>
              <span className={styles.legendSwatchWarm} />
              Backend SST cell surface
            </div>
            <div className={styles.legendItem}>
              <span
                className={styles.legendSwatch}
                style={{ background: "linear-gradient(135deg, rgba(255,196,96,0.6), rgba(255,255,255,0.95))" }}
              />
              Temperature break intensity
            </div>
            <div className={styles.legendItem}>
              <span
                className={styles.legendSwatch}
                style={{ background: "linear-gradient(135deg, rgba(83,255,182,0.55), rgba(244,255,158,0.9))" }}
              />
              Chlorophyll break intensity
            </div>
            <div className={styles.legendItem}>
              <span className={styles.legendSwatch} style={{ background: "rgba(255, 255, 255, 0.68)" }} />
              Nautical seamark raster
            </div>
          </div>
          {sstMapData?.metadata.temp_range_f && (
            <p className={styles.controlHint}>
              Visible SST range {sstMapData.metadata.temp_range_f[0].toFixed(1)}-
              {sstMapData.metadata.temp_range_f[1].toFixed(1)} F across {sstMapData.metadata.cell_count} cells from{" "}
              {sstMapData.metadata.point_count} SST points.
              {sstMapData.metadata.grid_resolution &&
                ` Grid ${sstMapData.metadata.grid_resolution[0]} x ${sstMapData.metadata.grid_resolution[1]}.`}
            </p>
          )}
          {sstMapData?.metadata.break_intensity_range && (
            <p className={styles.controlHint}>
              Break intensity range {sstMapData.metadata.break_intensity_range[0].toFixed(3)}-
              {sstMapData.metadata.break_intensity_range[1].toFixed(3)} F/nm.
            </p>
          )}
          {chlorophyllBreakMapData?.metadata.break_intensity_range_mg_m3_per_nm && (
            <p className={styles.controlHint}>
              Chlorophyll break range {chlorophyllBreakMapData.metadata.break_intensity_range_mg_m3_per_nm[0].toFixed(3)}-
              {chlorophyllBreakMapData.metadata.break_intensity_range_mg_m3_per_nm[1].toFixed(3)} mg/m3/nm.
            </p>
          )}
        </div>
      </div>

      <div className={styles.mapFeedback}>
        {isZonesLoading && <p className={styles.loadingBanner}>Refreshing zone rankings...</p>}
        {isSstMapLoading && <p className={styles.loadingBanner}>Refreshing SST overlay...</p>}
        {isChlorophyllBreakMapLoading && <p className={styles.loadingBanner}>Refreshing chlorophyll break overlay...</p>}
        {zonesError && <p className={styles.errorBanner}>{zonesError}</p>}
        {mapRuntimeError && <p className={styles.errorBanner}>{mapRuntimeError}</p>}
        {chlorophyllBreakMapError && <p className={styles.errorBanner}>{chlorophyllBreakMapError}</p>}
        {!overlayUnavailable && !isSstMapLoading && !hasOverlayCells && (
          <p className={styles.loadingBanner}>No SST overlay cells were returned for the current map request.</p>
        )}
        {overlayUnavailable && (
          <p className={styles.errorBanner}>
            SST overlay unavailable. Zone markers remain active while the backend falls back or recovers.
          </p>
        )}
      </div>
    </>
  );
}
