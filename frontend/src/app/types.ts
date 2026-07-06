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
}
