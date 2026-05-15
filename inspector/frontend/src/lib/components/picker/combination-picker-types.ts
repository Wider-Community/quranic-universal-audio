import type { PublicBucket, PublicDelivery, PublicReciter } from '../../types/public-state';

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
