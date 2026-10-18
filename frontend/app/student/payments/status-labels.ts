import type { Schema } from "./finance-api";

export type Lang = "en" | "id";
export type Label = Record<Lang, string>;

export function pickLang(value: string | string[] | undefined): Lang {
  return value === "id" ? "id" : "en";
}

export const paymentStateLabels: Record<Schema["PaymentState"], Label> = {
  DRAFT: { en: "Draft", id: "Draf" },
  AWAITING_APPROVAL: { en: "Waiting for sponsor approval", id: "Menunggu persetujuan sponsor" },
  AUTHORIZED: { en: "Approved, not yet sent", id: "Disetujui, belum dikirim" },
  ON_HOLD: { en: "Held for review", id: "Ditahan untuk ditinjau" },
  PROCESSING: { en: "Provider is processing", id: "Penyedia sedang memproses" },
  DELIVERED: { en: "Provider delivered", id: "Penyedia telah mengirim" },
  FAILED: { en: "Failed, funds returned", id: "Gagal, dana dikembalikan" },
  OUTCOME_UNKNOWN: { en: "Outcome unknown, checking", id: "Hasil belum diketahui, sedang dicek" },
  REJECTED: { en: "Rejected", id: "Ditolak" },
  EXPIRED: { en: "Expired", id: "Kedaluwarsa" },
  CANCELLED: { en: "Cancelled", id: "Dibatalkan" },
};

export const tuitionStateLabels: Record<Schema["TuitionState"], Label> = {
  UNPAID: { en: "Unpaid", id: "Belum dibayar" },
  AWAITING_POSTING: { en: "University awaiting posting", id: "Universitas menunggu pencatatan" },
  PARTIALLY_POSTED: { en: "Partly credited", id: "Sebagian tercatat" },
  PAID: { en: "Tuition paid", id: "Uang kuliah lunas" },
  EXCEPTION: { en: "Needs attention", id: "Perlu perhatian" },
  RECONCILIATION_PENDING: { en: "Reconciliation pending", id: "Rekonsiliasi berjalan" },
  ESCALATED: { en: "Escalated to the university", id: "Dieskalasi ke universitas" },
};

export const caseStateLabels: Record<Schema["CaseState"], Label> = {
  OPEN: { en: "Open", id: "Dibuka" },
  EVIDENCE_REQUIRED: { en: "Evidence needed", id: "Butuh bukti" },
  READY: { en: "Ready to submit", id: "Siap diajukan" },
  SUBMITTED: { en: "Submitted", id: "Diajukan" },
  UNDER_REVIEW: { en: "Under university review", id: "Ditinjau universitas" },
  RESOLVED: { en: "Resolved", id: "Selesai" },
  REJECTED: { en: "Rejected", id: "Ditolak" },
  NEEDS_INFO: { en: "More information needed", id: "Butuh informasi tambahan" },
  ESCALATED: { en: "Escalated", id: "Dieskalasi" },
};

export const safeNextStep: Record<Schema["ReasonCode"], Label> = {
  INVALID_SCOPE: { en: "This action is not available to you.", id: "Tindakan ini tidak tersedia untuk Anda." },
  UNKNOWN_BENEFICIARY: { en: "The payee is not verified. Use the verified university payee.", id: "Penerima belum terverifikasi. Gunakan penerima universitas yang terverifikasi." },
  BENEFICIARY_MISMATCH: { en: "The payee does not match the registry. Do not pay; ask for a review.", id: "Penerima tidak cocok dengan registri. Jangan bayar; minta peninjauan." },
  FUNDING_OWNER_APPROVAL_REQUIRED: { en: "Ask the funding owner to approve the exact terms.", id: "Minta pemilik dana menyetujui rincian yang tepat." },
  APPROVAL_EXPIRED: { en: "The approval expired. Request a new one.", id: "Persetujuan kedaluwarsa. Minta persetujuan baru." },
  APPROVAL_TERMS_MISMATCH: { en: "The terms changed. A new approval is needed.", id: "Rincian berubah. Perlu persetujuan baru." },
  QUOTE_EXPIRED: { en: "The simulated quote expired. Request a new quote.", id: "Kuotasi simulasi kedaluwarsa. Minta kuotasi baru." },
  INSUFFICIENT_FUNDS: { en: "The funding account cannot cover this. Ask the owner.", id: "Rekening dana tidak mencukupi. Tanyakan pemiliknya." },
  LIMIT_EXCEEDED: { en: "A spending limit blocks this payment. Ask the owner.", id: "Batas pengeluaran menahan pembayaran ini. Tanyakan pemiliknya." },
  SECURITY_HOLD: { en: "A security review is needed before anything is sent.", id: "Perlu tinjauan keamanan sebelum apa pun dikirim." },
  UNIVERSITY_POLICY_UNKNOWN: { en: "The university rules cannot be confirmed. Wait for confirmation.", id: "Aturan universitas belum dapat dipastikan. Tunggu konfirmasi." },
  PROVIDER_OUTCOME_UNKNOWN: { en: "Do not pay again. Check the status of the earlier payment.", id: "Jangan bayar lagi. Cek status pembayaran sebelumnya." },
  PAYMENT_ALREADY_SUBMITTED: { en: "A payment already exists. Check its status instead.", id: "Pembayaran sudah ada. Cek statusnya." },
  RECONCILIATION_NEEDS_INFO: { en: "An earlier payment needs reconciliation. Do not pay again.", id: "Pembayaran sebelumnya perlu rekonsiliasi. Jangan bayar lagi." },
  POSTING_WINDOW_ACTIVE: { en: "The university is still posting. Do not pay again; recheck later.", id: "Universitas masih mencatat. Jangan bayar lagi; cek lagi nanti." },
  TOPUP_NOT_PERMITTED: { en: "A top-up is not allowed here. Contact the university office.", id: "Penambahan dana tidak diizinkan. Hubungi kantor universitas." },
  IDEMPOTENCY_KEY_REUSED: { en: "This request key was used for another request. Retry from the page.", id: "Kunci permintaan ini dipakai permintaan lain. Coba lagi dari halaman." },
};

export const ui = {
  title: { en: "Payments and tuition status", id: "Pembayaran dan status uang kuliah" },
  simulated: { en: "Simulated: no real money, bank or university is involved.", id: "Simulasi: tidak ada uang, bank, atau universitas sungguhan." },
  provider: { en: "Payment provider", id: "Penyedia pembayaran" },
  university: { en: "University record", id: "Catatan universitas" },
  due: { en: "Amount due", id: "Jumlah tagihan" },
  posted: { en: "Credited by the university", id: "Tercatat oleh universitas" },
  remaining: { en: "Remaining", id: "Sisa" },
  deadline: { en: "Posting deadline", id: "Batas pencatatan" },
  quotes: { en: "Simulated quotes (total cost compared)", id: "Kuotasi simulasi (total biaya dibandingkan)" },
  receipt: { en: "Receipt", id: "Bukti" },
  recheck: { en: "Recheck status", id: "Cek ulang status" },
  openCase: { en: "Open a reconciliation case", id: "Buka kasus rekonsiliasi" },
  submitCase: { en: "Submit the case", id: "Ajukan kasus" },
  noPay: { en: "Provider delivery is not the same as tuition paid. Do not pay again.", id: "Pengiriman penyedia tidak sama dengan uang kuliah lunas. Jangan bayar lagi." },
  signIn: { en: "Sign in to see your payments.", id: "Masuk untuk melihat pembayaran Anda." },
  unavailable: { en: "The payment service is not available right now. No payment was sent.", id: "Layanan pembayaran belum tersedia. Tidak ada pembayaran yang dikirim." },
  none: { en: "No tuition obligation found.", id: "Tidak ada tagihan uang kuliah." },
  total: { en: "Total", id: "Total" },
  fee: { en: "Fee", id: "Biaya" },
  principal: { en: "Converted amount", id: "Jumlah dikonversi" },
  recipient: { en: "Recipient receives", id: "Penerima mendapat" },
  expires: { en: "Expires", id: "Berakhir" },
  eta: { en: "Estimated delivery", id: "Perkiraan tiba" },
  rate: { en: "Rate", id: "Kurs" },
  activityTitle: { en: "What happened", id: "Yang terjadi" },
  plantDocument: { en: "Plant untrusted document", id: "Tanam dokumen tidak tepercaya" },
  chooseRoute: { en: "Choose this route", id: "Pilih rute ini" },
  requestTopup: { en: "Request a top-up with this route", id: "Minta tambahan dana dengan rute ini" },
  changeRoute: { en: "Switch to this route", id: "Ganti ke rute ini" },
  payFrom: { en: "Pay from", id: "Bayar dari" },
  requestApproval: { en: "Ask the funding owner to approve", id: "Minta pemilik dana menyetujui" },
  shortfallTitle: { en: "A shortfall remains", id: "Masih ada kekurangan" },
  cancelIntent: { en: "Cancel this payment request", id: "Batalkan permintaan pembayaran ini" },
  continueIntent: { en: "Continue the approved payment", id: "Lanjutkan pembayaran yang disetujui" },
  youPay: { en: "You pay", id: "Anda membayar" },
  receives: { en: "University receives", id: "Universitas menerima" },
  payee: { en: "Verified payee", id: "Penerima terverifikasi" },
  fundedByYou: { en: "Paid from your account", id: "Dibayar dari rekening Anda" },
  fundedByOwner: { en: "Paid from the funding owner's account", id: "Dibayar dari rekening pemilik dana" },
  waitingOwner: { en: "Waiting for the funding owner's approval of these exact terms.", id: "Menunggu persetujuan pemilik dana atas rincian ini." },
  untrustedTitle: { en: "Messages you received (untrusted)", id: "Pesan yang Anda terima (tidak tepercaya)" },
  untrustedNote: { en: "Shown as plain text only. These messages cannot approve payments, change payees or remove holds.", id: "Hanya ditampilkan sebagai teks. Pesan ini tidak dapat menyetujui pembayaran, mengubah penerima, atau menghapus penahanan." },
  sender: { en: "Claimed sender", id: "Pengirim yang diklaim" },
  steps: {
    sponsor: { en: "Sponsor approval", id: "Persetujuan sponsor" },
    provider: { en: "Provider delivered", id: "Penyedia mengirim" },
    posting: { en: "University posting", id: "Pencatatan universitas" },
    reconciliation: { en: "Reconciliation", id: "Rekonsiliasi" },
    paid: { en: "Tuition paid", id: "Uang kuliah lunas" },
  },
} satisfies Record<string, Label | Record<string, Label>>;

// Audit actions are open-ended strings from the backend; unknown ones fall back to the raw code.
export const actionLabels: Record<string, Label> = {
  INTENT_CREATED: { en: "Payment request created", id: "Permintaan pembayaran dibuat" },
  INTENT_CANCELLED: { en: "Request cancelled", id: "Permintaan dibatalkan" },
  INTENT_SUPERSEDED: { en: "Replaced by a new route", id: "Diganti dengan rute baru" },
  INTENT_REFUSED: { en: "Request refused", id: "Permintaan ditolak" },
  PAYMENT_DEBITED: { en: "Funds debited (simulated)", id: "Dana didebit (simulasi)" },
  EXECUTION_REFUSED: { en: "Payment refused before any debit", id: "Pembayaran ditolak sebelum didebit" },
  TRANSFER_DELIVERED: { en: "Provider delivered", id: "Penyedia telah mengirim" },
  TRANSFER_FAILED: { en: "Provider failed, funds returned", id: "Penyedia gagal, dana dikembalikan" },
  TRANSFER_OUTCOME_UNKNOWN: { en: "Outcome unknown, being checked", id: "Hasil belum diketahui, sedang dicek" },
  RECONCILIATION_CASE_OPENED: { en: "Reconciliation case opened", id: "Kasus rekonsiliasi dibuka" },
  RECONCILIATION_SUBMITTED: { en: "Case submitted to the university", id: "Kasus diajukan ke universitas" },
  RECONCILIATION_REVIEWED: { en: "University reviewed the case", id: "Universitas meninjau kasus" },
  RECONCILIATION_ESCALATED: { en: "Case escalated", id: "Kasus dieskalasi" },
};
