import type { PublicDelivery, PublicReciter } from '../../types/generated/schemas';
import type { PublicBucket } from '../../types/public-bucket';

/** One row in the combination picker — a `(reciter, delivery)` pair. */
export interface CombinationSelection {
    kind: 'combination';
    reciter: PublicReciter;
    delivery: PublicDelivery;
}

export interface InitialFilter {
    bucket?: PublicBucket;
    search?: string;
}
