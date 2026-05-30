// frontend/src/components/visit-modal.tsx
"use client";

import React, { useState, useEffect } from "react";
import { Check, X, MapPin, MessageSquare, AlertCircle, Wifi, WifiOff } from "lucide-react";

interface VisitModalProps {
  isOpen: boolean;
  onClose: () => void;
  segmentData: {
    id: number;
    name: string;
    length_m: number;
    visited_by_user: boolean;
    notes?: string;
  } | null;
  onSave: (notes: string, visited: boolean) => void;
  isOffline: boolean;
}

export default function VisitModal({
  isOpen,
  onClose,
  segmentData,
  onSave,
  isOffline
}: VisitModalProps) {
  const [visited, setVisited] = useState(false);
  const [notes, setNotes] = useState("");

  useEffect(() => {
    if (segmentData) {
      setVisited(segmentData.visited_by_user);
      setNotes(segmentData.notes || "");
    }
  }, [segmentData]);

  if (!isOpen || !segmentData) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSave(notes, visited);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-0 sm:p-4 bg-black/60 backdrop-blur-sm animate-fade-in">
      <div className="w-full sm:max-w-md bg-zinc-950 border-t sm:border border-zinc-800/80 rounded-t-3xl sm:rounded-3xl shadow-2xl p-6 flex flex-col gap-4 animate-slide-up sm:animate-scale-up">
        {/* Header */}
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center">
              <MapPin className="w-5 h-5 text-primary" />
            </div>
            <div>
              <h3 className="text-sm font-extrabold text-white leading-tight">
                {segmentData.name || "Segmento de Calle"}
              </h3>
              <span className="text-[10px] text-zinc-400 font-bold block mt-0.5 leading-none">
                Longitud: {segmentData.length_m.toFixed(1)} metros
              </span>
            </div>
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 rounded-full bg-zinc-900 border border-zinc-800 flex items-center justify-center text-zinc-400 hover:text-white transition-all cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Offline Badge */}
        <div className={`flex items-center gap-1.5 px-3 py-2 rounded-xl text-[10px] font-bold ${
          isOffline 
            ? "bg-amber-500/10 border border-amber-500/20 text-amber-400" 
            : "bg-emerald-500/10 border border-emerald-500/20 text-emerald-400"
        }`}>
          {isOffline ? (
            <>
              <WifiOff className="w-3.5 h-3.5" />
              <span>Modo Offline: Guardando de forma local en IndexedDB. Se sincronizará al reconectar.</span>
            </>
          ) : (
            <>
              <Wifi className="w-3.5 h-3.5" />
              <span>Conexión Online: La visita se sincronizará directamente con el servidor.</span>
            </>
          )}
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          {/* Visited Toggle */}
          <div className="flex items-center justify-between p-4 bg-zinc-900 border border-zinc-800/60 rounded-2xl">
            <div className="flex flex-col">
              <span className="text-xs font-bold text-white">¿Calle Visitada?</span>
              <span className="text-[9px] text-zinc-400 font-medium mt-0.5">
                Marcar si pasaste por aquí con tu dispositivo
              </span>
            </div>
            <button
              type="button"
              onClick={() => setVisited(!visited)}
              className={`w-14 h-8 rounded-full p-1 transition-all duration-300 ${
                visited ? "bg-emerald-500" : "bg-zinc-800"
              }`}
            >
              <div className={`w-6 h-6 rounded-full bg-white flex items-center justify-center shadow-md transition-all duration-300 ${
                visited ? "translate-x-6" : "translate-x-0"
              }`}>
                {visited && <Check className="w-4 h-4 text-emerald-600 font-bold" />}
              </div>
            </button>
          </div>

          {/* Notes Area */}
          <div className="flex flex-col gap-1.5">
            <label className="text-[10px] uppercase font-bold text-zinc-400 tracking-wider flex items-center gap-1">
              <MessageSquare className="w-3.5 h-3.5 text-zinc-500" />
              Notas de campo / Observaciones
            </label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Ej: Tráfico lento, comercios cerrados, etc."
              rows={3}
              className="w-full bg-zinc-900 border border-zinc-800 rounded-2xl px-4 py-3 text-xs text-white placeholder-zinc-500 focus:outline-none focus:border-primary/50 transition-all resize-none"
            />
          </div>

          {/* Action buttons */}
          <div className="flex gap-3 mt-2">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 py-3 rounded-xl border border-zinc-800 bg-zinc-900 hover:bg-zinc-800/80 text-zinc-300 hover:text-white font-bold text-xs transition-all cursor-pointer text-center"
            >
              Cancelar
            </button>
            <button
              type="submit"
              className="flex-1 py-3 rounded-xl bg-primary hover:bg-primary/90 text-white font-black text-xs shadow-lg shadow-primary/20 transition-all cursor-pointer text-center"
            >
              {isOffline ? "Guardar en Cola" : "Guardar Registro"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
