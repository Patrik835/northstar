import type { AssetOption } from "./AssetPicker";

export type AssetCatalogue = {
  generated_at: string;
  stock_count: number;
  crypto_count: number;
  assets: AssetOption[];
};

let catalogueRequest: Promise<AssetCatalogue> | null = null;

export function loadAssetCatalogue(): Promise<AssetCatalogue> {
  if (!catalogueRequest) {
    catalogueRequest = fetch(`${import.meta.env.BASE_URL}asset-catalogue.json`)
      .then(async (response) => {
        if (!response.ok) throw new Error("Asset list unavailable");
        const catalogue: AssetCatalogue = await response.json();
        if (catalogue.stock_count !== 3000 || catalogue.crypto_count !== 150
          || !Array.isArray(catalogue.assets) || catalogue.assets.length !== 3150) {
          throw new Error("Asset list incomplete");
        }
        return catalogue;
      })
      .catch((error) => {
        catalogueRequest = null;
        throw error;
      });
  }
  return catalogueRequest;
}
