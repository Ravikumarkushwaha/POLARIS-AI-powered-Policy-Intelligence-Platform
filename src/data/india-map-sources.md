# Atlas data provenance

Retrieved 2026-09-14. Rendering is a simplified orientation map, not a survey product.

- Base geometry and Indian claimed-boundary depiction for Jammu and Kashmir / Ladakh: https://github.com/AbhinavSwami28/india-official-geojson/blob/main/india-states-simplified.geojson . Upstream MIT notice retained in india-map-LICENSE.txt. The upstream data references india-in-data/kashmir and Subhash9325/GeoJson-Data-of-Indian-States.
- Andhra Pradesh and Telangana: district polygons from https://github.com/udit-001/india-maps-data/tree/main/geojson/states . Districts dissolved with Shapely unary_union, invalid rings repaired with buffer(0), simplified at 0.008 degrees with topology preservation. This community repository attributes its geometry to publicly available sources and provides no separate license notice; boundaries are factual geospatial data. Preserve this attribution and review upstream provenance before external redistribution.
- Dadra and Nagar Haveli / Daman and Diu polygons combined into their current single union territory. Odisha, Uttarakhand and Andaman and Nicobar Islands names normalized. Final feature count: 36.

Claimed boundaries do not represent universal recognition or administrative control. The atlas labels disputed areas. Geographic weights are separate AI-generated heuristics and are never derived from polygon area. Historical combined-region model weights are not copied to newly separate regions.
