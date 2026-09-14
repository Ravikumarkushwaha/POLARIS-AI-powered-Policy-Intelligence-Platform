import { useMemo, useState } from "react";

import { normalizeState } from "@/lib/state-geography";
import geo from "@/data/india-states.geo.json";

type Geometry =
  | { type: "Polygon"; coordinates: number[][][] }
  | { type: "MultiPolygon"; coordinates: number[][][][] };

type Feature = {
  type: "Feature";
  properties: { name: string };
  geometry: Geometry;
};

function colorFor(score: number) {
  const t = Math.max(0, Math.min(100, score)) / 100;
  return `hsl(${190 + t * 55} ${55 + t * 25}% ${75 - t * 35}%)`;
}

export function IndiaMap({
  stateImpact,
  selected,
  onSelect,
}: {
  stateImpact: Record<string, number> | null;
  selected?: string;
  onSelect?: (state: string) => void;
}) {
  const [hover, setHover] = useState<string | null>(null);
  const [relief, setRelief] = useState(true);
  const [zoom, setZoom] = useState(1);
  const features = (geo as unknown as { features: Feature[] }).features;

  const { paths } = useMemo(() => {
    const width = 760;
    const height = 820;
    const merc = (lon: number, lat: number): [number, number] => [
      (lon * Math.PI) / 180,
      Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360)),
    ];

    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;

    const eachRing = (geometry: Geometry, fn: (ring: number[][]) => void) => {
      if (geometry.type === "Polygon") {
        for (const ring of geometry.coordinates) fn(ring as number[][]);
      } else if (geometry.type === "MultiPolygon") {
        for (const poly of geometry.coordinates) for (const ring of poly) fn(ring as number[][]);
      }
    };

    for (const feature of features) {
      eachRing(feature.geometry, (ring) => {
        for (const [lon, lat] of ring) {
          const [x, y] = merc(lon as number, lat as number);
          if (x < minX) minX = x;
          if (x > maxX) maxX = x;
          if (y < minY) minY = y;
          if (y > maxY) maxY = y;
        }
      });
    }

    const scale = Math.min(width / (maxX - minX), height / (maxY - minY));
    const offsetX = (width - (maxX - minX) * scale) / 2;
    const offsetY = (height - (maxY - minY) * scale) / 2;
    const project = (lon: number, lat: number) => {
      const [x, y] = merc(lon, lat);
      return [(x - minX) * scale + offsetX, height - offsetY - (y - minY) * scale] as const;
    };

    return {
      paths: features.map((feature) => {
        let d = "";
        eachRing(feature.geometry, (ring) => {
          ring.forEach(([lon, lat], i) => {
            const [px, py] = project(lon as number, lat as number);
            d += `${i === 0 ? "M" : "L"}${px.toFixed(2)},${py.toFixed(2)}`;
          });
          d += "Z";
        });
        return { name: feature.properties.name, d };
      }),
    };
  }, [features]);

  const lookup = useMemo(() => {
    const map = new Map<string, number>();
    for (const [key, value] of Object.entries(stateImpact ?? {})) {
      map.set(normalizeState(key), value);
    }
    return map;
  }, [stateImpact]);

  return (
    <section className="panel relative overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="label-eyebrow">Interactive atlas</div>
          <h2 className="mt-1 text-lg font-semibold">India, in focus</h2>
        </div>
        <button
          className="control-button rounded-full border px-3 py-1.5 text-xs"
          onClick={() => setRelief(!relief)}
          aria-pressed={relief}
        >
          {relief ? "3D relief" : "Flat map"}
        </button>
      </div>
      <div
        className="atlas-stage relative mt-4 overflow-auto rounded-2xl border"
        style={{ perspective: 1100 }}
      >
        <svg
          viewBox="-24 -24 808 868"
          role="group"
          aria-label="Select an Indian state or union territory"
          className="block max-h-[610px] min-h-[340px] w-full origin-center motion-safe:transition-transform"
          style={{
            transform: relief ? "rotateX(12deg) rotateZ(-3deg)" : undefined,
            width: `${zoom * 100}%`,
            maxHeight: zoom > 1 ? "none" : undefined,
          }}
        >
          {relief && (
            <g transform="translate(0,9)" fill="hsl(210 35% 24%)" opacity="0.4" aria-hidden="true">
              {paths.map((p) => (
                <path key={p.name} d={p.d} />
              ))}
            </g>
          )}
          {paths.map((p) => {
            const score = lookup.get(normalizeState(p.name));
            const active = normalizeState(selected ?? "") === normalizeState(p.name);
            return (
              <path
                key={p.name}
                d={p.d}
                role="button"
                tabIndex={0}
                aria-label={`${p.name}: ${score == null ? "no estimate" : `${score.toFixed(1)} relative exposure`}`}
                aria-pressed={active}
                fill={active ? "#00cbb8" : score == null ? "#b5c1d0" : colorFor(score)}
                stroke={active ? "#0e5e63" : "#ffffff"}
                strokeWidth={active ? 2.5 : 0.85}
                style={{
                  transform: active && relief ? "translateY(-7px)" : undefined,
                  filter: active ? "drop-shadow(0 6px 4px #0f172a55)" : undefined,
                }}
                className="cursor-pointer outline-none motion-safe:transition-[fill,transform] hover:brightness-110 focus:stroke-primary focus:stroke-[3px]"
                onMouseEnter={() => setHover(p.name)}
                onMouseLeave={() => setHover(null)}
                onFocus={() => setHover(p.name)}
                onBlur={() => setHover(null)}
                onClick={() => onSelect?.(p.name)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onSelect?.(p.name);
                  }
                }}
              >
                <title>{p.name}</title>
              </path>
            );
          })}
        </svg>
        <div className="pointer-events-none absolute left-3 top-3 rounded-xl border border-border/70 bg-card/75 px-3 py-2 text-xs shadow-lg backdrop-blur-xl">
          {hover ?? selected ?? "Choose a region to explore"}
        </div>
      </div>
      <div className="mt-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
          <span>Lower exposure</span>
          <span
            className="h-2 w-16 rounded-full"
            style={{ background: `linear-gradient(to right, ${colorFor(0)}, ${colorFor(100)})` }}
          />
          <span>Higher</span>
        </div>
        <div className="flex gap-1">
          <button
            aria-label="Zoom out"
            className="control-button rounded-lg border px-3 py-1"
            onClick={() => setZoom(Math.max(1, zoom - 0.5))}
            disabled={zoom === 1}
          >
            -
          </button>
          <button
            className="control-button rounded-lg border px-2 text-xs"
            onClick={() => setZoom(1)}
          >
            Reset
          </button>
          <button
            aria-label="Zoom in"
            className="control-button rounded-lg border px-3 py-1"
            onClick={() => setZoom(Math.min(2.5, zoom + 0.5))}
            disabled={zoom === 2.5}
          >
            +
          </button>
        </div>
      </div>
      <p className="mt-3 text-[10px] leading-5 text-muted-foreground">
        Indian boundary depiction includes claimed territories; some areas are disputed and
        administered elsewhere. Grey indicates no estimate.{" "}
        <a
          className="underline"
          href="https://github.com/AbhinavSwami28/india-official-geojson"
          target="_blank"
          rel="noreferrer"
        >
          Map source
        </a>
      </p>
    </section>
  );
}
