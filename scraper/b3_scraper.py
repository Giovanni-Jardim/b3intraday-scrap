#!/usr/bin/env python3
"""
B3 Intraday Scraper - GitHub Actions Edition
Automação de dados para AmiBroker
"""

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import os
import sys
import json
from pathlib import Path
import time

class B3GitHubScraper:
    def __init__(self, data_dir="data/intraday"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Lista de ativos da B3 para monitorar
        # Pode ser configurada via variável de ambiente
        self.default_tickers = [
            'PETR4', 'VALE3', 'ITUB4', 'BBDC4', 'ABEV3',
            'WEGE3', 'RENT3', 'LREN3', 'PRIO3', 'SUZB3',
            'RADL3', 'RAIL3', 'BBAS3', 'VIVT3', 'TOTS3'
        ]
        
        # Carrega configuração se existir
        self.config = self._load_config()
    
    def _load_config(self):
        """Carrega configuração de ativos via arquivo JSON ou env var"""
        config_file = Path("config/tickers.json")
        if config_file.exists():
            with open(config_file) as f:
                return json.load(f)
        
        # Ou usa variável de ambiente
        env_tickers = os.getenv('B3_TICKERS', '')
        if env_tickers:
            return {'tickers': env_tickers.split(',')}
        
        return {'tickers': self.default_tickers}
    
    def get_ticker_yf(self, ticker_b3):
        """Converte para formato Yahoo Finance"""
        return f"{ticker_b3.upper()}.SA"
    
    def fetch_intraday(self, ticker, interval='5m', max_retries=3):
        """
        Busca dados com retry logic para robustez em CI/CD
        """
        ticker_yf = self.get_ticker_yf(ticker)
        
        # Define período baseado no intervalo (limites Yahoo Finance)
        period_map = {
            '1m': '5d',    # 7 dias max, mas usamos 5 para segurança
            '5m': '20d',   # 60 dias max
            '15m': '30d',
            '30m': '60d',
            '1h': '730d'   # 2 anos
        }
        period = period_map.get(interval, '5d')
        
        for attempt in range(max_retries):
            try:
                print(f"📊 [{attempt+1}/{max_retries}] Baixando {ticker} ({interval})...")
                
                data = yf.download(
                    ticker_yf,
                    period=period,
                    interval=interval,
                    progress=False,
                    auto_adjust=False,
                    threads=False  # Importante para CI/CD
                )
                
                if data.empty:
                    print(f"⚠️ Sem dados para {ticker}")
                    return None
                
                # Ajusta colunas MultiIndex do yfinance
                if isinstance(data.columns, pd.MultiIndex):
                    data.columns = data.columns.get_level_values(0)
                
                # Remove timezone
                if data.index.tz is not None:
                    data.index = data.index.tz_localize(None)
                
                print(f"✅ {ticker}: {len(data)} registros ({data.index[0]} a {data.index[-1]})")
                return data
                
            except Exception as e:
                print(f"❌ Tentativa {attempt+1} falhou: {e}")
                if attempt < max_retries - 1:
                    time.sleep(5)  # Aguarda antes de retry
                else:
                    print(f"🚫 Falha definitiva em {ticker}")
                    return None
    
    def export_amibroker_format(self, df, ticker, interval='5m'):
        """
        Exporta no formato ASCII compatível com AmiBroker
        Formato: Date, Time, Open, High, Low, Close, Volume
        """
        if df is None or df.empty:
            return None
        
        # Prepara dados
        df_export = df.copy()
        
        # Garante colunas necessárias
        required = ['Open', 'High', 'Low', 'Close', 'Volume']
        if not all(col in df_export.columns for col in required):
            print(f"❌ Colunas necessárias não encontradas em {ticker}")
            return None
        
        # Formata data e hora
        df_export['Date'] = df_export.index.strftime('%Y-%m-%d')
        df_export['Time'] = df_export.index.strftime('%H:%M:%S')
        
        # Reordena
        df_export = df_export[['Date', 'Time', 'Open', 'High', 'Low', 'Close', 'Volume']]
        
        # Nome do arquivo: TICKER_INTERVAL_YYYYMMDD.txt
        date_suffix = datetime.now().strftime('%Y%m%d')
        filename = f"{ticker}_{interval}_{date_suffix}.txt"
        filepath = self.data_dir / filename
        
        # Exporta sem cabeçalho (formato AmiBroker puro)
        df_export.to_csv(filepath, index=False, header=False, sep=',')
        
        # Também cria versão consolidada (append)
        consolidated = self.data_dir / f"{ticker}_{interval}_consolidated.txt"
        header = not consolidated.exists()
        df_export.to_csv(consolidated, index=False, header=header, sep=',', mode='a')
        
        print(f"💾 Salvo: {filename} ({len(df)} linhas)")
        return filepath
    
    def generate_summary(self, results):
        """Gera resumo da execução para o GitHub Actions"""
        summary = {
            'timestamp': datetime.now().isoformat(),
            'total_tickers': len(self.config['tickers']),
            'success': [],
            'failed': []
        }
        
        for ticker, df in results.items():
            if df is not None:
                summary['success'].append({
                    'ticker': ticker,
                    'records': len(df),
                    'date_range': f"{df.index[0]} a {df.index[-1]}"
                })
            else:
                summary['failed'].append(ticker)
        
        # Salva JSON de resumo
        summary_file = self.data_dir / f"summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2, default=str)
        
        # Output para GitHub Actions
        if os.getenv('GITHUB_ACTIONS'):
            print(f"\n::set-output name=success_count::{len(summary['success'])}")
            print(f"::set-output name=failed_count::{len(summary['failed'])}")
            
            # MarkDown summary para GitHub
            print(f"\n### 📈 Resumo Coleta B3")
            print(f"- ✅ Sucesso: {len(summary['success'])} ativos")
            print(f"- ❌ Falhas: {len(summary['failed'])} ativos")
            print(f"\n**Ativos processados:**")
            for s in summary['success']:
                print(f"- {s['ticker']}: {s['records']} registros")
        
        return summary
    
    def run(self, interval='5m', tickers=None):
        """Executa coleta completa"""
        tickers = tickers or self.config['tickers']
        results = {}
        
        print(f"🚀 Iniciando coleta B3 - {datetime.now()}")
        print(f"📋 Ativos: {', '.join(tickers)}")
        print(f"⏱️ Intervalo: {interval}")
        print("=" * 50)
        
        for ticker in tickers:
            df = self.fetch_intraday(ticker, interval)
            if df is not None:
                self.export_amibroker_format(df, ticker, interval)
            results[ticker] = df
            time.sleep(2)  # Respeita rate limit entre requisições
        
        print("\n" + "=" * 50)
        summary = self.generate_summary(results)
        
        # Retorna exit code apropriado
        failed = len(summary['failed'])
        if failed == len(tickers):
            print("🚨 Todos os ativos falharam!")
            return 1
        elif failed > 0:
            print(f"⚠️ {failed} ativos falharam, mas continuando...")
        
        return 0


def main():
    """Entry point para CLI"""
    import argparse
    parser = argparse.ArgumentParser(description='B3 Intraday Scraper')
    parser.add_argument('--interval', default='5m', help='Timeframe (1m, 5m, 15m, 1h)')
    parser.add_argument('--tickers', nargs='+', help='Lista de tickers específicos')
    parser.add_argument('--data-dir', default='data/intraday', help='Diretório de saída')
    args = parser.parse_args()
    
    scraper = B3GitHubScraper(data_dir=args.data_dir)
    exit_code = scraper.run(interval=args.interval, tickers=args.tickers)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()