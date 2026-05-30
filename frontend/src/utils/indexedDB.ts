// frontend/src/utils/indexedDB.ts
// Native 0-dependency IndexedDB wrapper for offline Street Tracking cache and sync queue

const DB_NAME = "LondrinaRadarOfflineDB";
const DB_VERSION = 1;

export interface OfflineVisit {
  segment_id: number;
  visited: boolean;
  visited_at: string;
  notes: string;
  source: string;
}

let dbInstance: IDBDatabase | null = null;

function getDB(): Promise<IDBDatabase> {
  if (dbInstance) return Promise.resolve(dbInstance);

  return new Promise((resolve, reject) => {
    if (typeof window === "undefined") {
      reject("IndexedDB is only available in the browser context.");
      return;
    }

    const request = indexedDB.open(DB_NAME, DB_VERSION);

    request.onupgradeneeded = (event: any) => {
      const db = event.target.result;
      if (!db.objectStoreNames.contains("segments_cache")) {
        db.createObjectStore("segments_cache", { keyPath: "bbox" });
      }
      if (!db.objectStoreNames.contains("pending_visits")) {
        db.createObjectStore("pending_visits", { keyPath: "segment_id" });
      }
    };

    request.onsuccess = (event: any) => {
      dbInstance = event.target.result;
      resolve(dbInstance!);
    };

    request.onerror = (event: any) => {
      reject(event.target.error);
    };
  });
}

// ------------------------------------------------------------------------------
// STREET SEGMENTS GEOMETRY CACHE
// ------------------------------------------------------------------------------
export async function cacheSegments(bbox: string, geojson: any): Promise<void> {
  try {
    const db = await getDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction("segments_cache", "readwrite");
      const store = tx.objectStore("segments_cache");
      store.put({ bbox, geojson, timestamp: Date.now() });

      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  } catch (err) {
    console.error("IndexedDB cacheSegments error:", err);
  }
}

export async function getCachedSegments(bbox: string): Promise<any | null> {
  try {
    const db = await getDB();
    return new Promise((resolve) => {
      const tx = db.transaction("segments_cache", "readonly");
      const store = tx.objectStore("segments_cache");
      const request = store.get(bbox);

      request.onsuccess = () => {
        resolve(request.result ? request.result.geojson : null);
      };
      request.onerror = () => {
        resolve(null);
      };
    });
  } catch (err) {
    console.error("IndexedDB getCachedSegments error:", err);
    return null;
  }
}

// ------------------------------------------------------------------------------
// OFFLINE VISITS QUEUE
// ------------------------------------------------------------------------------
export async function savePendingVisit(visit: OfflineVisit): Promise<void> {
  try {
    const db = await getDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction("pending_visits", "readwrite");
      const store = tx.objectStore("pending_visits");
      store.put(visit);

      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  } catch (err) {
    console.error("IndexedDB savePendingVisit error:", err);
  }
}

export async function getPendingVisits(): Promise<OfflineVisit[]> {
  try {
    const db = await getDB();
    return new Promise((resolve) => {
      const tx = db.transaction("pending_visits", "readonly");
      const store = tx.objectStore("pending_visits");
      const request = store.getAll();

      request.onsuccess = () => {
        resolve(request.result || []);
      };
      request.onerror = () => {
        resolve([]);
      };
    });
  } catch (err) {
    console.error("IndexedDB getPendingVisits error:", err);
    return [];
  }
}

export async function removePendingVisit(segmentId: number): Promise<void> {
  try {
    const db = await getDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction("pending_visits", "readwrite");
      const store = tx.objectStore("pending_visits");
      store.delete(segmentId);

      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  } catch (err) {
    console.error("IndexedDB removePendingVisit error:", err);
  }
}

export async function clearPendingVisits(): Promise<void> {
  try {
    const db = await getDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction("pending_visits", "readwrite");
      const store = tx.objectStore("pending_visits");
      store.clear();

      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  } catch (err) {
    console.error("IndexedDB clearPendingVisits error:", err);
  }
}
