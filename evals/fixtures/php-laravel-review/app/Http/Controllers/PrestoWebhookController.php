<?php

namespace App\Http\Controllers;

use App\Models\Order;
use Illuminate\Http\Request;

final class PrestoWebhookController
{
    public function __invoke(Request $request)
    {
        $event = $request->all();
        $order = Order::where('txn_ref_num', $event['txnRefNum'])->firstOrFail();
        if ($event['eventCode'] === 'Authorised') {
            $order->status = 'paid';
            $order->save();
            $order->ship();
        }
        return response()->json(['resend' => false]);
    }
}
