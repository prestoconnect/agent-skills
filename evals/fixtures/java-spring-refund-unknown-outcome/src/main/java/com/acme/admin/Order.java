package com.acme.admin;

import jakarta.persistence.Entity;
import jakarta.persistence.Id;

@Entity
public class Order {
    @Id
    private Long id;
    private String txnRefNum;
    private String paymentRefNum;
    private long amountCents;
    private String status;

    public Long getId() { return id; }
    public String getTxnRefNum() { return txnRefNum; }
    public String getPaymentRefNum() { return paymentRefNum; }
    public long getAmountCents() { return amountCents; }
    public String getStatus() { return status; }
}
