package httpapi

import (
    "encoding/json"
    "net/http"
)

type Event struct {
    EventCode string
    TxnRefNum string
}

type OrderStore interface {
    MarkPaid(txnRefNum string) error
    Ship(txnRefNum string) error
}

type Handler struct {
    Orders OrderStore
}

func (h *Handler) PrestoNotify(w http.ResponseWriter, r *http.Request) {
    var event Event
    if err := json.NewDecoder(r.Body).Decode(&event); err != nil {
        http.Error(w, "bad request", http.StatusBadRequest)
        return
    }
    if event.EventCode == "Authorised" {
        if err := h.Orders.MarkPaid(event.TxnRefNum); err != nil {
            http.Error(w, "database error", http.StatusInternalServerError)
            return
        }
        if err := h.Orders.Ship(event.TxnRefNum); err != nil {
            http.Error(w, "shipping error", http.StatusInternalServerError)
            return
        }
    }
    w.WriteHeader(http.StatusOK)
}
