"use client";

import L from "leaflet";
import "leaflet/dist/leaflet.css";
import "leaflet-draw";
import "leaflet-draw/dist/leaflet.draw.css";
import { useEffect, useMemo, useRef } from "react";
import {
  FeatureGroup,
  GeoJSON,
  MapContainer,
  TileLayer,
  useMap,
  useMapEvents,
  ZoomControl,
} from "react-leaflet";

import type { GeoJsonFeatureCollection } from "@/lib/api/types";

export type MapDrawTool = "polygon" | "rectangle" | null;

type MapCanvasProps = {
  zones: GeoJsonFeatureCollection | null;
  addresses: GeoJsonFeatureCollection | null;
  flyTo: { lat: number; lng: number; zoom?: number } | null;
  selectedZoneId: string | null;
  activeDrawTool: MapDrawTool;
  onDrawToolChange: (tool: MapDrawTool) => void;
  onViewportChange: (bbox: string, zoom: number) => void;
  onZoneClick: (zoneId: string) => void;
  onAddressClick: (rcCode: number, label: string) => void;
  onDrawPolygon: (geojson: Record<string, unknown>) => void;
  onDrawRectangle: (geojson: Record<string, unknown>) => void;
  onMapBackgroundClick: () => void;
  showZones: boolean;
  showAddresses: boolean;
  drawResetToken: number;
};

function zoneStyle(
  offerings: Array<{ status?: string; technology_color?: string }> | undefined,
  isSelected: boolean,
): L.PathOptions {
  const borderColor = offerings?.[0]?.technology_color ?? "#6b7280";
  const statuses = (offerings ?? []).map((item) => item.status);
  const hasOffering = statuses.length > 0;
  const fillOpacity = hasOffering ? 0.28 : 0.18;

  if (isSelected) {
    return {
      color: "#2563eb",
      weight: 3,
      fillColor: borderColor,
      fillOpacity: 0.4,
    };
  }

  return {
    color: borderColor,
    weight: 2,
    fillColor: borderColor,
    fillOpacity,
  };
}

const LT_CENTER: [number, number] = [54.3072, 25.3866];

export function MapCanvas({
  zones,
  addresses,
  flyTo,
  selectedZoneId,
  activeDrawTool,
  onDrawToolChange,
  onViewportChange,
  onZoneClick,
  onAddressClick,
  onDrawPolygon,
  onDrawRectangle,
  onMapBackgroundClick,
  showZones,
  showAddresses,
  drawResetToken,
}: MapCanvasProps): React.JSX.Element {
  const drawLayerRef = useRef<L.FeatureGroup | null>(null);

  useEffect(() => {
    void drawResetToken;
    drawLayerRef.current?.clearLayers();
  }, [drawResetToken]);

  const zonesKey = useMemo(() => {
    if (!zones) return "empty";
    const selection = selectedZoneId ?? "none";
    return `${selection}|${zones.features
      .map((feature) => {
        const properties = feature.properties as {
          id?: string;
          offerings?: Array<{
            status?: string;
            technology_type?: string;
            technology_color?: string;
          }>;
        };
        const offerings = (properties.offerings ?? [])
          .map(
            (item) =>
              `${item.technology_type ?? ""}:${item.status ?? ""}:${item.technology_color ?? ""}`,
          )
          .join(";");
        return `${properties.id ?? ""}#${offerings}`;
      })
      .join("|")}`;
  }, [zones, selectedZoneId]);

  const addressesKey = useMemo(() => {
    if (!addresses) return "empty";
    const features = addresses.features;
    let hash = `${features.length}`;
    for (const feature of features) {
      const properties = feature.properties as {
        rc_code?: number;
        has_address_offering?: boolean;
        has_zone_offering?: boolean;
      };
      hash += `:${properties.rc_code ?? ""}=${properties.has_address_offering ? 1 : 0}${
        properties.has_zone_offering ? "z" : ""
      }`;
    }
    return hash;
  }, [addresses]);

  return (
    <MapContainer center={LT_CENTER} zoom={12} zoomControl={false} className="h-full w-full">
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <ZoomControl position="bottomright" />
      <MapViewportObserver
        activeDrawTool={activeDrawTool}
        onViewportChange={onViewportChange}
        onMapBackgroundClick={onMapBackgroundClick}
      />
      <MapFlyTo flyTo={flyTo} />

      <FeatureGroup
        ref={(instance) => {
          drawLayerRef.current = instance as unknown as L.FeatureGroup | null;
        }}
      >
        <MapDrawController
          activeDrawTool={activeDrawTool}
          drawLayerRef={drawLayerRef}
          onDrawToolChange={onDrawToolChange}
          onDrawPolygon={onDrawPolygon}
          onDrawRectangle={onDrawRectangle}
        />
      </FeatureGroup>

      {showZones && zones ? (
        <GeoJSON
          key={zonesKey}
          data={zones as unknown as GeoJSON.GeoJsonObject}
          style={(feature) => {
            const properties = (feature?.properties ?? {}) as {
              id?: string;
              offerings?: Array<{ status?: string }>;
            };
            return zoneStyle(
              properties.offerings,
              Boolean(properties.id && properties.id === selectedZoneId),
            );
          }}
          onEachFeature={(feature, layer) => {
            const properties = (feature.properties ?? {}) as {
              id?: string;
              name?: string;
              offerings?: Array<{ status?: string }>;
            };
            if (properties.name) {
              layer.bindTooltip(properties.name, {
                sticky: true,
                opacity: 0.92,
              });
            }
            if (properties.id) {
              layer.on("click", (event) => {
                L.DomEvent.stopPropagation(event);
                onZoneClick(properties.id as string);
              });
              if (properties.id === selectedZoneId) {
                (layer as L.Path).bringToFront();
              }
            }
          }}
        />
      ) : null}

      {showAddresses && addresses ? (
        <GeoJSON
          key={addressesKey}
          data={addresses as unknown as GeoJSON.GeoJsonObject}
          pointToLayer={(feature, latlng) => {
            const properties = (feature.properties ?? {}) as {
              has_address_offering?: boolean;
              has_zone_offering?: boolean;
            };
            const color = properties.has_address_offering
              ? "#1d4ed8"
              : properties.has_zone_offering
                ? "#22c55e"
                : "#64748b";
            return L.circleMarker(latlng, {
              radius: 4,
              weight: 1,
              color,
              fillOpacity: 0.9,
            });
          }}
          onEachFeature={(feature, layer) => {
            const properties = (feature.properties ?? {}) as { rc_code?: number; label?: string };
            if (properties.label) {
              layer.bindPopup(properties.label);
            }
            if (properties.rc_code) {
              layer.on("click", (event) => {
                L.DomEvent.stopPropagation(event);
                onAddressClick(properties.rc_code as number, (properties.label as string) ?? "");
              });
            }
          }}
        />
      ) : null}
    </MapContainer>
  );
}

function MapDrawController({
  activeDrawTool,
  drawLayerRef,
  onDrawToolChange,
  onDrawPolygon,
  onDrawRectangle,
}: {
  activeDrawTool: MapDrawTool;
  drawLayerRef: React.RefObject<L.FeatureGroup | null>;
  onDrawToolChange: (tool: MapDrawTool) => void;
  onDrawPolygon: (geojson: Record<string, unknown>) => void;
  onDrawRectangle: (geojson: Record<string, unknown>) => void;
}): null {
  const map = useMap();
  const handlerRef = useRef<L.Draw.Polygon | L.Draw.Rectangle | null>(null);
  const onDrawPolygonRef = useRef(onDrawPolygon);
  const onDrawRectangleRef = useRef(onDrawRectangle);
  const onDrawToolChangeRef = useRef(onDrawToolChange);

  useEffect(() => {
    onDrawPolygonRef.current = onDrawPolygon;
    onDrawRectangleRef.current = onDrawRectangle;
    onDrawToolChangeRef.current = onDrawToolChange;
  }, [onDrawPolygon, onDrawRectangle, onDrawToolChange]);

  useEffect(() => {
    handlerRef.current?.disable();
    handlerRef.current = null;

    if (!activeDrawTool) {
      return;
    }

    const featureGroup = drawLayerRef.current;
    if (!featureGroup) {
      return;
    }

    let created = false;
    const shapeOptions: L.PathOptions =
      activeDrawTool === "polygon"
        ? { color: "#2563eb", weight: 2, fillColor: "#2563eb", fillOpacity: 0.15 }
        : { color: "#7c3aed", weight: 2, fillColor: "#7c3aed", fillOpacity: 0.12, dashArray: "6 4" };

    const drawMap = map as L.DrawMap;
    const handler =
      activeDrawTool === "polygon"
        ? new L.Draw.Polygon(drawMap, {
            allowIntersection: false,
            showArea: false,
            shapeOptions,
          })
        : new L.Draw.Rectangle(drawMap, { shapeOptions });

    handlerRef.current = handler;

    const onCreated = (event: L.LeafletEvent): void => {
      created = true;
      const drawEvent = event as L.DrawEvents.Created;
      const layer = drawEvent.layer;
      featureGroup.addLayer(layer);
      const feature = layer.toGeoJSON() as { geometry?: Record<string, unknown> };
      const geometry = feature.geometry ?? {};
      if (activeDrawTool === "rectangle") {
        onDrawRectangleRef.current(geometry);
      } else {
        onDrawPolygonRef.current(geometry);
      }
      handler.disable();
      onDrawToolChangeRef.current(null);
    };

    const onDrawStop = (): void => {
      if (!created) {
        onDrawToolChangeRef.current(null);
      }
    };

    map.on(L.Draw.Event.CREATED, onCreated);
    map.on(L.Draw.Event.DRAWSTOP, onDrawStop);
    handler.enable();

    return () => {
      map.off(L.Draw.Event.CREATED, onCreated);
      map.off(L.Draw.Event.DRAWSTOP, onDrawStop);
      handler.disable();
    };
  }, [activeDrawTool, drawLayerRef, map]);

  return null;
}

function MapViewportObserver({
  activeDrawTool,
  onViewportChange,
  onMapBackgroundClick,
}: {
  activeDrawTool: MapDrawTool;
  onViewportChange: (bbox: string, zoom: number) => void;
  onMapBackgroundClick: () => void;
}): null {
  const map = useMapEvents({
    moveend: () => {
      const bounds = map.getBounds();
      const sw = bounds.getSouthWest();
      const ne = bounds.getNorthEast();
      onViewportChange(`${sw.lng},${sw.lat},${ne.lng},${ne.lat}`, map.getZoom());
    },
    zoomend: () => {
      const bounds = map.getBounds();
      const sw = bounds.getSouthWest();
      const ne = bounds.getNorthEast();
      onViewportChange(`${sw.lng},${sw.lat},${ne.lng},${ne.lat}`, map.getZoom());
    },
    click: () => {
      if (activeDrawTool) {
        return;
      }
      onMapBackgroundClick();
    },
  });

  useEffect(() => {
    const bounds = map.getBounds();
    const sw = bounds.getSouthWest();
    const ne = bounds.getNorthEast();
    onViewportChange(`${sw.lng},${sw.lat},${ne.lng},${ne.lat}`, map.getZoom());
  }, [map, onViewportChange]);

  return null;
}

function MapFlyTo({ flyTo }: { flyTo: { lat: number; lng: number; zoom?: number } | null }): null {
  const map = useMap();

  useEffect(() => {
    if (!flyTo) {
      return;
    }
    map.flyTo([flyTo.lat, flyTo.lng], flyTo.zoom ?? 17, {
      duration: 0.8,
    });
  }, [flyTo, map]);

  return null;
}
