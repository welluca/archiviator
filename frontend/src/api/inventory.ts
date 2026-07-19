import apiClient from './client';
import type { Entity, ValuationOut } from '../types';

export const inventoryApi = {
  /** Add delta to the quantity (floors at 0 server-side). Any entity kind. */
  async quantityAdjust(entityId: number, delta: number): Promise<Entity> {
    const { data } = await apiClient.post<Entity>(
      `/entities/${entityId}/quantity-adjust`,
      { delta }
    );
    return data;
  },

  /** Consumables at/below their threshold, worst ratio first. */
  async lowStock(): Promise<Entity[]> {
    const { data } = await apiClient.get<Entity[]>('/inventory/low-stock');
    return data;
  },

  /** Value rollup (current_value ?? purchase_price ?? 0), sold/archived excluded. */
  async valuation(): Promise<ValuationOut> {
    const { data } = await apiClient.get<ValuationOut>('/inventory/valuation');
    return data;
  },

  /** Last 10 non-archived entities by created_at. */
  async recent(): Promise<Entity[]> {
    const { data } = await apiClient.get<Entity[]>('/inventory/recent');
    return data;
  },
};
