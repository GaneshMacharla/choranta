import { PaymentOrder } from '../../services/plans';
import { portalService } from '../../services/portal';

declare global {
  interface Window {
    Razorpay?: any;
  }
}

const CHECKOUT_SRC = 'https://checkout.razorpay.com/v1/checkout.js';

const loadCheckoutScript = () =>
  new Promise<void>((resolve, reject) => {
    if (window.Razorpay) return resolve();
    const existing = document.querySelector(`script[src="${CHECKOUT_SRC}"]`) as HTMLScriptElement | null;
    const script = existing || document.createElement('script');
    script.addEventListener('load', () => resolve());
    script.addEventListener('error', () => reject(new Error('Could not load Razorpay. Check your connection and try again.')));
    if (!existing) {
      script.src = CHECKOUT_SRC;
      script.async = true;
      document.head.appendChild(script);
    }
  });

/**
 * Opens Razorpay Checkout for an order and verifies the payment with the backend.
 * Resolves true when paid and verified, false if the person closed Checkout.
 */
export async function payWithRazorpay(order: PaymentOrder): Promise<boolean> {
  await loadCheckoutScript();
  return new Promise<boolean>((resolve, reject) => {
    const checkout = new window.Razorpay({
      key: order.key_id,
      order_id: order.razorpay_order_id,
      amount: order.amount_paise,
      currency: order.currency,
      name: order.company_name,
      description: order.description,
      prefill: order.prefill,
      theme: { color: '#00df8f' },
      handler: (response: { razorpay_payment_id: string; razorpay_signature: string }) => {
        portalService
          .verifyPayment(order.order_id, response.razorpay_payment_id, response.razorpay_signature)
          .then(() => resolve(true))
          .catch(reject);
      },
      modal: { ondismiss: () => resolve(false) },
    });
    // A failed attempt stays inside Checkout, which lets the person retry or close it
    checkout.open();
  });
}
