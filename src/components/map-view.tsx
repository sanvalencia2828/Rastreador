import { Map, Source, Layer, Marker, Popup } from 'react-map-gl/maplibre';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { useState } from 'react';
import { Target, MapPin, Layers3 } from 'lucide-react';

// URL del mapa base oscuro de CartoDB (100% Gratuito y Open Source)
const MAP_STYLE = '[https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json](https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json)';

interface MapViewProps {
  heatmapData: any;
  clustersData: any[];
}

export default function MapView({ heatmapData, clustersData }: MapViewProps) {
  const [selectedCluster, setSelectedCluster] = useState<any>(null);
  const [viewState, setViewState] = useState({
    longitude: -51.1628, // Londrina Centro
    latitude: -23.3102,
    zoom: 12
  });

  const onSelectCluster = (cluster: any) => {
    try {
      const coords = JSON.parse(cluster.center_geom).coordinates;
      setSelectedCluster(cluster);
      setViewState({
        ...viewState,
        longitude: coords[0],
        latitude: coords[1],
        zoom: 15, // Zoom suave al polo comercial
      });
    } catch (e) {
      console.error("Error al procesar coordenadas", e);
    }
  };

  return (
    <div className="w-full h-full relative bg-slate-950">
      <Map onMove={evt => setViewState(evt.viewState)}
        mapLib={maplibregl} // <--- Crucial: Usar el motor de MapLibre
        mapStyle={MAP_STYLE}
        style={{ width: '100%', height: '100%' }}
      >

        {heatmapData && (
          <Source data={heatmapData} type="geojson">
            <Layer id="heatmap-layer" type="heatmap" paint={{
              'heatmap-weight': 1,
              'heatmap-intensity': [
                'interpolate',
                ['linear'],
                ['zoom'],
                0, 1,
                9, 1.5,
                15, 3.5
              ],
              'heatmap-color': [
                'interpolate',
                ['linear'],
                ['heatmap-density'],
                0, 'rgba(0,0,0,0)',
                0.2, 'rgb(0, 255, 255)',
                0.6, 'rgb(0, 255, 0)',
                0.9, 'rgb(255, 255, 0)',
                1.8, 'rgb(255, 0, 0)'
              ],
              'heatmap-radius': [
                'interpolate',
                ['linear'],
                ['zoom'],
                0, 2,
                9, 10,
                15, 30
              ]
            }} />
          </Source>
        )}


        {clustersData?.map((cluster) => {
          try {
            const coords = JSON.parse(cluster.center_geom).coordinates;
            return (
              <Marker key={cluster.cluster_id} latitude={coords[1]} longitude={coords[0]}>
                <button
                  onClick={() => onSelectCluster(cluster)}
                  className="bg-amber-600 text-white rounded-full h-10 w-10 flex items-center justify-center font-bold shadow-xl border-2 border-slate-900 text-sm transform hover:scale-110 transition-transform cursor-pointer"
                >
                  {cluster.total_lojas}
                </button>
              </Marker>
            );
          } catch (e) {
            return null;
          }
        })}


        {selectedCluster && (
          <div className="absolute bottom-6 right-6 z-50">
            <div className="bg-slate-900/90 backdrop-blur-sm border border-slate-800 p-5 rounded-2xl shadow-2xl text-white w-72">
              <div className="flex items-center gap-3 mb-3">
                <div className="bg-amber-600 p-2.5 rounded-xl">
                  <Layers3 className="h-5 w-5"/>
                </div>
                <div>
                  <div className="text-sm font-semibold">Polo Comercial #{selectedCluster.cluster_id}</div>
                  <div className="text-xs text-slate-400">Londrina Periferia</div>
                </div>
              </div>
              <div className="space-y-2 mb-4 text-sm text-slate-300">
                <p><strong>Total Tiendas:</strong> {selectedCluster.total_lojas}</p>
                <p className="text-xs text-emerald-400 font-medium">Estimación Alta Densidad Territorial</p>
              </div>
              <button
                onClick={() => setSelectedCluster(null)}
                className="w-full bg-slate-700 hover:bg-slate-600 text-white text-xs px-4 py-2 rounded-lg font-medium transition-colors"
              >
                Cerrar Panel
              </button>
            </div>
          </div>
        )}
      </Map>
    </div>
  );
}