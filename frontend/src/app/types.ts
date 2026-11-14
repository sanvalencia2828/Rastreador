export interface Stop {
  id: string;
  address: string;
  lat: number;
  lon: number;
  displayName: string;
  cep: string | null;
  businesses: Business[];
  loadingBusinesses: boolean;
}

export interface Business {
  cnpj: string;
  nome_fantasia: string;
  cnae_label: string;
  cnae_icon: string;
  bairro: string;
  logradouro: string;
  municipio: string;
  lat: number;
  lon: number;
  distance_m: number;
  status?: "new" | "visited" | "client";
}

export interface SavedRouteStop {
  id: string;
  stop_order: number;
  address: string;
  lat: number;
  lon: number;
  cep: string | null;
  display_name: string | null;
}

export interface SavedRoute {
  id: string;
  name: string;
  city_id: number;
  created_at: string | null;
  stops: SavedRouteStop[];
}
