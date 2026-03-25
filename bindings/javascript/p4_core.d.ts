export interface Identity {
  private_key_b64: string;
  public_key_b64: string;
  peer_id: string;
}

export interface SignEnvelopeInput {
  privateKeyB64: string;
  senderPeerId: string;
  recipientPeerId: string;
  payload: Record<string, unknown>;
  timestampMs?: number;
  nonce: string;
}

export interface VerifyEnvelopeInput {
  envelope: Record<string, unknown>;
  signerPublicKeyB64: string;
  maxSkewMs?: number;
  nowMs?: number;
}

export class P4Core {
  constructor(libPath?: string);
  lastError(): string;
  generateIdentity(): Identity;
  peerIdFromPublicKeyB64(publicKeyB64: string): string;
  signEnvelope(input: SignEnvelopeInput): Record<string, unknown>;
  verifyEnvelope(input: VerifyEnvelopeInput): boolean;
}

export function resolveOnionrelayPath(pathOverride?: string): string;

