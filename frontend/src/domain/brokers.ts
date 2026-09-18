import type { Broker } from "../api/types";
import binanceLogo from "../assets/brokers/binance.svg";
import bybitLogo from "../assets/brokers/bybit.svg";
import etoroLogo from "../assets/brokers/etoro.svg";
import interactiveBrokersLogo from "../assets/brokers/interactive-brokers.svg";
import scalableCapitalLogo from "../assets/brokers/scalable-capital.svg";
import tradeRepublicLogo from "../assets/brokers/trade-republic.svg";
import trading212Logo from "../assets/brokers/trading212.svg";
import xtbLogo from "../assets/brokers/xtb.svg";

type BrokerMetadata = {
  name: string;
  shortMark: string;
  logo?: string;
};

export const brokerMetadata: Record<Broker, BrokerMetadata> = {
  trading212: { name: "Trading 212", shortMark: "T2", logo: trading212Logo },
  trading212_crypto: {
    name: "Trading 212 Crypto",
    shortMark: "2C",
    logo: trading212Logo,
  },
  etoro: { name: "eToro", shortMark: "eT", logo: etoroLogo },
  binance: { name: "Binance", shortMark: "BN", logo: binanceLogo },
  bybit: { name: "Bybit", shortMark: "BY", logo: bybitLogo },
  interactive_brokers: {
    name: "Interactive Brokers",
    shortMark: "IB",
    logo: interactiveBrokersLogo,
  },
  xtb: { name: "XTB", shortMark: "XT", logo: xtbLogo },
  trade_republic: {
    name: "Trade Republic",
    shortMark: "TR",
    logo: tradeRepublicLogo,
  },
  scalable_capital: {
    name: "Scalable Capital",
    shortMark: "SC",
    logo: scalableCapitalLogo,
  },
};

export const brokers = Object.keys(brokerMetadata) as Broker[];

export function brokerName(broker: Broker): string {
  return brokerMetadata[broker].name;
}

export function brokerShortMark(broker: Broker): string {
  return brokerMetadata[broker].shortMark;
}

export function brokerLogo(broker: Broker): string | undefined {
  return brokerMetadata[broker].logo;
}

export function brokerNameFromValue(value: string): string {
  return value in brokerMetadata
    ? brokerName(value as Broker)
    : value;
}
