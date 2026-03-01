from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime
from decimal import Decimal

from src.models import (
    AssetFifoReport,
    FifoMatch,
    OpenLot,
    PortfolioFifoReport,
    RealizedSaleReport,
)
from src.models import NormalizedTransaction


class FifoEngine:
    def build_report(self, transactions: list[NormalizedTransaction]) -> PortfolioFifoReport:
        sorted_transactions = sorted(transactions, key=lambda tx: tx.timestamp)

        lots_by_isin: dict[str, deque[OpenLot]] = defaultdict(deque)
        realized_sales_by_isin: dict[str, list[RealizedSaleReport]] = defaultdict(list)

        for tx in sorted_transactions:
            if tx.transaction_type not in {"buy", "sell"}:
                continue

            if tx.transaction_type == "buy":
                lots_by_isin[tx.isin].append(self._build_open_lot(tx))
                continue

            sale_report = self._consume_sale(tx, lots_by_isin[tx.isin])
            realized_sales_by_isin[tx.isin].append(sale_report)

        assets: list[AssetFifoReport] = []
        all_realized_sales: list[RealizedSaleReport] = []

        for isin in sorted(set(lots_by_isin.keys()) | set(realized_sales_by_isin.keys())):
            realized_sales = realized_sales_by_isin.get(isin, [])
            open_lots = list(lots_by_isin.get(isin, deque()))
            name = self._resolve_asset_name(realized_sales, open_lots)

            realized_gain_total = sum(
                (sale.total_realized_gain for sale in realized_sales), Decimal("0")
            )
            open_quantity_total = sum((lot.quantity_remaining for lot in open_lots), Decimal("0"))
            open_cost_total = sum(
                (lot.quantity_remaining * lot.unit_cost for lot in open_lots), Decimal("0")
            )

            assets.append(
                AssetFifoReport(
                    isin=isin,
                    name=name,
                    realized_sales=realized_sales,
                    open_lots=open_lots,
                    realized_gain_total=realized_gain_total,
                    open_quantity_total=open_quantity_total,
                    open_cost_total=open_cost_total,
                )
            )
            all_realized_sales.extend(realized_sales)

        total_realized_gain = sum((sale.total_realized_gain for sale in all_realized_sales), Decimal("0"))
        total_cost_basis = sum((sale.total_cost_basis for sale in all_realized_sales), Decimal("0"))
        total_proceeds = sum((sale.total_proceeds for sale in all_realized_sales), Decimal("0"))

        return PortfolioFifoReport(
            generated_at=datetime.now(),
            assets=assets,
            realized_sales=all_realized_sales,
            total_realized_gain=total_realized_gain,
            total_cost_basis=total_cost_basis,
            total_proceeds=total_proceeds,
        )

    def filter_report_by_fiscal_year(
        self,
        report: PortfolioFifoReport,
        fiscal_year: int,
    ) -> PortfolioFifoReport:
        filtered_assets: list[AssetFifoReport] = []
        filtered_realized_sales: list[RealizedSaleReport] = []

        for asset in report.assets:
            # 1. Sales in this year
            asset_realized_sales = [
                sale
                for sale in asset.realized_sales
                if sale.sell_transaction.timestamp.year == fiscal_year
            ]

            # 2. Check if it was held during this year and calculate open quantity/cost as of this year.
            # An asset was held if:
            # - It had realized sales during this year.
            # - Its aggregated open quantity as of the end of this year is > 0.
            
            historical_open_lots: list[OpenLot] = []
            as_of_quantity = Decimal("0")
            as_of_cost = Decimal("0")
            
            # Dictionary to track historical remaining quantity by the original buy transaction
            # We index by the source transaction's timestamp since it's unique per lot in our engine
            lot_historical_remaining: dict[datetime, Decimal] = defaultdict(Decimal)
            
            # 2a. Add current open lots that were bought in or before this year.
            # Their current `quantity_remaining` is the baseline. We will add back sales that happened later.
            for lot in asset.open_lots:
                if lot.timestamp.year <= fiscal_year:
                    # Make a shallow copy/reconstruction to avoid mutating the original
                    historical_lot = OpenLot(
                        timestamp=lot.timestamp,
                        isin=lot.isin,
                        name=lot.name,
                        quantity_total=lot.quantity_total,
                        quantity_remaining=lot.quantity_remaining,
                        unit_cost=lot.unit_cost,
                        source_transaction=lot.source_transaction
                    )
                    historical_open_lots.append(historical_lot)
                    lot_historical_remaining[lot.timestamp] = lot.quantity_remaining
                    
            # 2b. Add back quantities of lots that were fully or partially sold AFTER this year, 
            # but were bought in or before this year.
            # We use `asset.realized_sales` which contains the matches.
            for sale in asset.realized_sales:
                if sale.sell_transaction.timestamp.year > fiscal_year:
                    for match in sale.matches:
                        if match.buy_timestamp.year <= fiscal_year:
                            # This match represents quantity that was SOLD in the future, 
                            # meaning it was STILL OPEN at the end of `fiscal_year`.
                            # We need to add it to our historical open lots.
                            
                            # Check if we already have a historical lot for this buy
                            # (e.g., it was partially open currently)
                            existing_lot = next((l for l in historical_open_lots if l.timestamp == match.buy_timestamp), None)
                            
                            if existing_lot:
                                existing_lot.quantity_remaining += match.quantity
                                lot_historical_remaining[match.buy_timestamp] += match.quantity
                            else:
                                # We need to reconstruct the lot from the match data
                                # Note: `quantity_total` might be inaccurate if we only see a partial match of a fully closed lot,
                                # but usually we piece it together or just use what we have.
                                # Matches track `buy_timestamp` and `buy_unit_cost`. 
                                # We can fake a source transaction or just use minimal info since UI only needs specific fields.
                                # To do it perfectly, we should look it up from ALL lots, but `asset.open_lots` only has CURRENT ones.
                                # We can reconstruct a minimal `OpenLot`.
                                
                                # Let's create a proxy NormalizedTransaction
                                proxy_tx = NormalizedTransaction(
                                    timestamp=match.buy_timestamp,
                                    isin=match.isin,
                                    name=match.name,
                                    quantity=match.quantity, # Not accurate for 'total', but we don't know the real total
                                    price_per_share=match.buy_unit_cost, # Approx, excludes separated fees
                                    commissions=Decimal("0"),
                                    total_amount=Decimal("0"),
                                    broker=match.buy_broker,
                                    currency="EUR",
                                    transaction_type="buy"
                                )
                                
                                new_lot = OpenLot(
                                    timestamp=match.buy_timestamp,
                                    isin=match.isin,
                                    name=match.name,
                                    quantity_total=match.quantity,
                                    quantity_remaining=match.quantity,
                                    unit_cost=match.buy_unit_cost,
                                    source_transaction=proxy_tx
                                )
                                historical_open_lots.append(new_lot)
                                lot_historical_remaining[match.buy_timestamp] = match.quantity

            # Sort historical open lots by timestamp just like the engine does
            historical_open_lots.sort(key=lambda l: l.timestamp)

            # Recalculate totals based on the reconstructed historical lots
            for lot in historical_open_lots:
                as_of_quantity += lot.quantity_remaining
                as_of_cost += (lot.quantity_remaining * lot.unit_cost)
            
            is_active = (as_of_quantity > 0) or (len(asset_realized_sales) > 0)


            if not is_active:
                continue

            asset_realized_gain_total = sum(
                (sale.total_realized_gain for sale in asset_realized_sales), Decimal("0")
            )

            filtered_asset = AssetFifoReport(
                isin=asset.isin,
                name=asset.name,
                realized_sales=asset_realized_sales,
                open_lots=historical_open_lots,
                realized_gain_total=asset_realized_gain_total,
                open_quantity_total=as_of_quantity,
                open_cost_total=as_of_cost,
            )
            filtered_assets.append(filtered_asset)
            filtered_realized_sales.extend(asset_realized_sales)

        total_realized_gain = sum(
            (sale.total_realized_gain for sale in filtered_realized_sales), Decimal("0")
        )
        total_cost_basis = sum((sale.total_cost_basis for sale in filtered_realized_sales), Decimal("0"))
        total_proceeds = sum((sale.total_proceeds for sale in filtered_realized_sales), Decimal("0"))

        return PortfolioFifoReport(
            generated_at=report.generated_at,
            assets=filtered_assets,
            realized_sales=filtered_realized_sales,
            total_realized_gain=total_realized_gain,
            total_cost_basis=total_cost_basis,
            total_proceeds=total_proceeds,
        )

    def _build_open_lot(self, tx: NormalizedTransaction) -> OpenLot:
        quantity = tx.quantity
        unit_buy_fee = self._per_share_fee(tx)
        unit_cost = tx.price_per_share + unit_buy_fee

        return OpenLot(
            timestamp=tx.timestamp,
            isin=tx.isin,
            name=tx.name,
            quantity_total=quantity,
            quantity_remaining=quantity,
            unit_cost=unit_cost,
            source_transaction=tx,
        )

    def _consume_sale(self, sale_tx: NormalizedTransaction, lots: deque[OpenLot]) -> RealizedSaleReport:
        quantity_to_match = sale_tx.quantity
        if quantity_to_match <= 0:
            raise ValueError(f"Sell quantity must be positive for {sale_tx.isin} at {sale_tx.timestamp}")

        unit_sell_fee = self._per_share_fee(sale_tx)
        unit_sell_net = sale_tx.price_per_share - unit_sell_fee

        matches: list[FifoMatch] = []

        while quantity_to_match > 0:
            if not lots:
                raise ValueError(
                    f"Insufficient holdings for sell: ISIN={sale_tx.isin}, "
                    f"sell_qty={sale_tx.quantity}, remaining={quantity_to_match}, timestamp={sale_tx.timestamp}"
                )

            lot = lots[0]
            consumed_quantity = min(lot.quantity_remaining, quantity_to_match)

            cost_basis = consumed_quantity * lot.unit_cost
            proceeds = consumed_quantity * unit_sell_net
            realized_gain = proceeds - cost_basis

            matches.append(
                FifoMatch(
                    isin=sale_tx.isin,
                    name=sale_tx.name,
                    quantity=consumed_quantity,
                    buy_timestamp=lot.timestamp,
                    sell_timestamp=sale_tx.timestamp,
                    buy_unit_cost=lot.unit_cost,
                    sell_unit_net=unit_sell_net,
                    cost_basis=cost_basis,
                    proceeds=proceeds,
                    realized_gain=realized_gain,
                    buy_broker=lot.source_transaction.broker,
                )
            )

            lot.quantity_remaining -= consumed_quantity
            quantity_to_match -= consumed_quantity

            if lot.quantity_remaining == 0:
                lots.popleft()

        total_quantity = sum((match.quantity for match in matches), Decimal("0"))
        total_cost_basis = sum((match.cost_basis for match in matches), Decimal("0"))
        total_proceeds = sum((match.proceeds for match in matches), Decimal("0"))
        total_realized_gain = sum((match.realized_gain for match in matches), Decimal("0"))

        return RealizedSaleReport(
            isin=sale_tx.isin,
            name=sale_tx.name,
            sell_transaction=sale_tx,
            matches=matches,
            total_quantity=total_quantity,
            total_cost_basis=total_cost_basis,
            total_proceeds=total_proceeds,
            total_realized_gain=total_realized_gain,
        )

    def _per_share_fee(self, tx: NormalizedTransaction) -> Decimal:
        if tx.quantity == 0:
            return Decimal("0")
        return abs(tx.commissions) / tx.quantity

    def _resolve_asset_name(
        self,
        realized_sales: list[RealizedSaleReport],
        open_lots: list[OpenLot],
    ) -> str:
        if open_lots:
            return open_lots[0].name
        if realized_sales:
            return realized_sales[0].name
        return ""
