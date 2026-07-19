import apiClient from './client';
import type {
  CellType,
  FloorPlan,
  FloorPlanDetail,
  FurnitureGrid,
  GridCell,
  MapRegion,
  Placement,
  PolygonPoint,
} from '../types';

export interface RegionPayload {
  /** >= 3 [x,y] image-pixel points within the image bounds (+ small tolerance). */
  polygon: PolygonPoint[];
  /** Label anchor override; null resets to the polygon centroid. */
  label_x?: number | null;
  label_y?: number | null;
}

export interface PlacementPayload {
  x: number;
  y: number;
  /** Positive; canvas coordinates. */
  w: number;
  h: number;
  rotation?: number;
  label_x?: number | null;
  label_y?: number | null;
}

export interface CreateGridPayload {
  entity_id: number;
  /** 1-12. */
  rows: number;
  /** 1-12. */
  cols: number;
  name?: string;
  /** Anchor cell for a stacked sub-grid — the cell must already be bound,
   * and entity_id must equal the cell's bound entity (409 otherwise). */
  parent_cell_id?: number;
  default_cell_type?: CellType;
}

export interface PatchGridPayload {
  name?: string | null;
  /** Growing adds cells; shrinking deletes only UNBOUND dropped cells (else 409). */
  rows?: number;
  cols?: number;
  sort_order?: number;
}

export interface PatchCellPayload {
  cell_type?: CellType;
  label?: string | null;
  /** Spans must not overlap other cells nor exceed grid bounds (409). */
  row_span?: number;
  col_span?: number;
}

/** {entity_id: N} binds an existing direct-child container; {auto: true}
 * creates + binds a container named from the label or '<CellType> r-c';
 * {entity_id: null} unbinds (the entity is untouched). */
export type BindCellPayload = { entity_id: number | null } | { auto: true };

export const mapApi = {
  /** All floor plans ordered by sort_order, id. */
  async listFloors(): Promise<FloorPlan[]> {
    const { data } = await apiClient.get<FloorPlan[]>('/map/floors');
    return data;
  },

  /** Create a floor for a space entity. With a file it's an image floor; with
   * file=null it's a blank canvas (drawn in-app), optionally sized. 409 if the
   * space already has a plan. */
  async createFloor(
    entityId: number,
    file: File | null,
    canvas?: { canvas_w?: number; canvas_h?: number }
  ): Promise<FloorPlan> {
    if (file === null) {
      const { data } = await apiClient.post<FloorPlan>('/map/floors', {
        entity_id: entityId,
        ...(canvas ?? {}),
      });
      return data;
    }
    const form = new FormData();
    form.append('file', file);
    form.append('entity_id', String(entityId));
    // Axios drops the JSON default Content-Type for FormData so the browser
    // sets the multipart boundary itself.
    const { data } = await apiClient.post<FloorPlan>('/map/floors', form);
    return data;
  },

  /** Replace the image only — the canvas frame and regions/placements are kept. */
  async replaceFloorImage(id: number, file: File): Promise<FloorPlan> {
    const form = new FormData();
    form.append('file', file);
    const { data } = await apiClient.patch<FloorPlan>(`/map/floors/${id}`, form);
    return data;
  },

  /** Drop the background image (back to blank canvas); layout is untouched. */
  async removeFloorImage(id: number): Promise<FloorPlan> {
    const { data } = await apiClient.delete<FloorPlan>(`/map/floors/${id}/image`);
    return data;
  },

  async patchFloor(id: number, payload: { sort_order: number }): Promise<FloorPlan> {
    const { data } = await apiClient.patch<FloorPlan>(`/map/floors/${id}`, payload);
    return data;
  },

  /** Regions cascade; the image file is removed when no other plan shares it. */
  async deleteFloor(id: number): Promise<void> {
    await apiClient.delete(`/map/floors/${id}`);
  },

  async getFloor(id: number): Promise<FloorPlanDetail> {
    const { data } = await apiClient.get<FloorPlanDetail>(`/map/floors/${id}`);
    return data;
  },

  /** Upsert the traced polygon of a room (a descendant space of the floor). */
  async putRegion(
    floorId: number,
    entityId: number,
    payload: RegionPayload
  ): Promise<MapRegion> {
    const { data } = await apiClient.put<MapRegion>(
      `/map/floors/${floorId}/regions/${entityId}`,
      payload
    );
    return data;
  },

  async deleteRegion(floorId: number, entityId: number): Promise<void> {
    await apiClient.delete(`/map/floors/${floorId}/regions/${entityId}`);
  },

  /** Upsert a furniture footprint (a non-space descendant of the floor). */
  async putPlacement(
    floorId: number,
    entityId: number,
    payload: PlacementPayload
  ): Promise<Placement> {
    const { data } = await apiClient.put<Placement>(
      `/map/floors/${floorId}/placements/${entityId}`,
      payload
    );
    return data;
  },

  async deletePlacement(floorId: number, entityId: number): Promise<void> {
    await apiClient.delete(`/map/floors/${floorId}/placements/${entityId}`);
  },

  /** Grids of one furniture/container entity (cells included). */
  async getGrids(entityId: number): Promise<FurnitureGrid[]> {
    const { data } = await apiClient.get<FurnitureGrid[]>('/map/grids', {
      params: { entity_id: entityId },
    });
    return data;
  },

  /** Creates the grid with all rows*cols cells. */
  async createGrid(payload: CreateGridPayload): Promise<FurnitureGrid> {
    const { data } = await apiClient.post<FurnitureGrid>('/map/grids', payload);
    return data;
  },

  async patchGrid(id: number, payload: PatchGridPayload): Promise<FurnitureGrid> {
    const { data } = await apiClient.patch<FurnitureGrid>(`/map/grids/${id}`, payload);
    return data;
  },

  /** Cells cascade; bound entities are NOT deleted — binding is a view link. */
  async deleteGrid(id: number): Promise<void> {
    await apiClient.delete(`/map/grids/${id}`);
  },

  async patchCell(id: number, payload: PatchCellPayload): Promise<GridCell> {
    const { data } = await apiClient.patch<GridCell>(`/map/cells/${id}`, payload);
    return data;
  },

  async bindCell(id: number, payload: BindCellPayload): Promise<GridCell> {
    const { data } = await apiClient.post<GridCell>(`/map/cells/${id}/bind`, payload);
    return data;
  },
};
