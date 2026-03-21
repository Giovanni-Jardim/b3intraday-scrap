#!/usr/bin/env python3
"""
B3 Intraday Scraper - GitHub Actions Edition
Corrigido: Conversão correta UTC → BRT (Brasília)
"""

import yfinance as yf
import pandas as pd
from datetime import datetime
import os
import sys
import json
from pathlib import Path
import time

class B3GitHubScraper:
    def __init__(self, data_dir="data/intraday"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.default_tickers = [
            'PETR4', 'VALE3', 'ITUB4', 'BBDC4', 'ABEV3',
            'WEGE3', 'RENT3', 'LREN3', 'PRIO3', 'SUZB3',
            'RADL3', 'RAIL3', 'BBAS3', 'VIVT3', 'TOTS3'
        ]
        
        self.config = self._load_config()
    
    def _load_config(self):
        config_file = Path("config/tickers.json")
        if config_file.exists():
            with open(config_file) as f:
                return json.load(f)
        
        env_tickers = os.getenv('B3_TICKERS', '')
        if env_tickers:
            return {'tickers': env_tickers.split(',')}
        
        return {'tickers': self.default_tickers}
    
    def get_ticker_yf(self, ticker_b3):
        return f"{ticker_b3.upper()}.SA"
    
    def fetch_intraday(self, ticker, interval='5m', max_retries=3):
        """
        Busca dados e converte de UTC para BRT (Brasília)
        """
        ticker_yf = self.get_ticker_yf(ticker)
        
        period_map = {
            '1m': '5d',
            '5m': '20d',
            '15m': '30d',
            '30m': '60d',
            '1h': '730d'
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
                    threads=False
                )
                
                if data.empty:
                    print(f"⚠️ Sem dados para {ticker}")
                    return None
                
                # Ajusta colunas MultiIndex
                if isinstance(data.columns, pd.MultiIndex):
                    data.columns = data.columns.get_level_values(0)
                
                # ============================================================
                # CORREÇÃO DO FUSO HORÁRIO: UTC → BRT (Brasília)
                # ============================================================
                
                # O Yahoo Finance retorna dados em UTC
                # B3 opera 10:00-17:00 BRT = 13:00-20:00 UTC
                
                if data.index.tz is None:
                    # Assume UTC se não tiver timezone
                    data.index = data.index.tz_localize('UTC')
                
                # Converte para BRT (Brasília, UTC-3)
                data.index = data.index.tz_convert('America/Sao_Paulo')
                
                # Remove timezone mantendo a hora local (BRT)
                data.index = data.index.tz_localize(None)
                
                # ============================================================
                
                # Filtra apenas horário de pregão (10:00 - 17:00 BRT)
                # Descomente se quiser apenas pregão regular:
                # data = data.between_time('10:00', '17:00')
                
                print(f"✅ {ticker}: {len(data)} registros ({data.index[0]} a {data.index[-1]})")
                print(f"   Horário: {data.index[0].strftime('%H:%M')} - {data.index[-1].strftime('%H:%M')} BRT")
                
                return data
                
            except Exception as e:
                print(f"❌ Tentativa {attempt+1} falhou: {e}")
                if attempt < max_retries - 1:
                    time.sleep(5)
                else:
                    print(f"🚫 Falha definitiva em {ticker}")
                    return None
    
    def export_amibroker_format(self, df, ticker, interval='5m'):
        """
        Exporta no formato ASCII: Ticker, Date, Time, Open, High, Low, Close, Volume
        Agora com horário BRT correto (10:00 início do pregão)
        """
        if df is None or df.empty:
            return None
        
        df_export = df.copy()
        
        required = ['Open', 'High', 'Low', 'Close', 'Volume']
        if not all(col in df_export.columns for col in required):
            print(f"❌ Colunas necessárias não encontradas em {ticker}")
            return None
        
        # Adiciona Ticker em todas as linhas
        df_export.insert(0, 'Ticker', ticker.upper())
        
        # Formata data e hora (já em BRT)
        df_export['Date'] = df_export.index.strftime('%Y-%m-%d')
        df_export['Time'] = df_export.index.strftime('%H:%M:%S')
        
        # Reordena: Ticker, Date, Time, Open, High, Low, Close, Volume
        df_export = df_export[['Ticker', 'Date', 'Time', 'Open', 'High', 'Low', 'Close', 'Volume']]
        
        # Salva arquivo do dia
        date_suffix = datetime.now().strftime('%Y%m%d')
        filename = f"{ticker}_{interval}_{date_suffix}.txt"
        filepath = self.data_dir / filename
        
        df_export.to_csv(filepath, index=False, header=False, sep=',')
        
        # Atualiza consolidated
        consolidated = self.data_dir / f"{ticker}_{interval}_consolidated.txt"
        if consolidated.exists():
            existing = pd.read_csv(consolidated, header=None, 
                                 names=['Ticker', 'Date', 'Time', 'Open', 'High', 'Low', 'Close', 'Volume'])
            combined = pd.concat([existing, df_export], ignore_index=True)
            combined = combined.drop_duplicates(subset=['Date', 'Time'], keep='last')
            combined.to_csv(consolidated, index=False, header=False, sep=',')
        else:
            df_export.to_csv(consolidated, index=False, header=False, sep=',')
        
        print(f"💾 Salvo: {filename} ({len(df)} linhas) | Horário BRT ✅")
        return filepath
    
    def generate_unified_file(self, all_data, interval='5m'):
        """Gera arquivo unificado com todos os tickers"""
        if not all_data:
            return None
        
        unified_df = pd.concat(all_data.values(), ignore_index=True)
        unified_df = unified_df.sort_values(['Ticker', 'Date', 'Time'])
        
        filename = f"UNIFIED_ALL_{interval}_{datetime.now().strftime('%Y%m%d')}.txt"
        filepath = self.data_dir / filename
        
        unified_df.to_csv(filepath, index=False, header=False, sep=',')
        print(f"🗂️  Arquivo unificado: {filename} ({len(unified_df)} registros)")
        
        # Consolidado unificado
        consolidated_unified = self.data_dir / f"UNIFIED_ALL_{interval}_consolidated.txt"
        if consolidated_unified.exists():
            existing = pd.read_csv(consolidated_unified, header=None, 
                                 names=['Ticker', 'Date', 'Time', 'Open', 'High', 'Low', 'Close', 'Volume'])
            combined = pd.concat([existing, unified_df], ignore_index=True)
            combined = combined.drop_duplicates(subset=['Ticker', 'Date', 'Time'], keep='last')
            combined = combined.sort_values(['Ticker', 'Date', 'Time'])
            combined.to_csv(consolidated_unified, index=False, header=False, sep=',')
        else:
            unified_df.to_csv(consolidated_unified, index=False, header=False, sep=',')
        
        return filepath
    
    def generate_summary(self, results):
        """Gera resumo da execução"""
        summary = {
            'timestamp': datetime.now().isoformat(),
            'total_tickers': len(self.config['tickers']),
            'success': [],
            'failed': []
        }
        
        all_data = {}
        for ticker, df in results.items():
            if df is not None:
                summary['success'].append({
                    'ticker': ticker,
                    'records': len(df),
                    'date_range': f"{df.index[0]} a {df.index[-1]}",
                    'time_range': f"{df.index[0].strftime('%H:%M')} - {df.index[-1].strftime('%H:%M')} BRT"
                })
                df_copy = df.copy()
                df_copy.insert(0, 'Ticker', ticker.upper())
                df_copy['Date'] = df_copy.index.strftime('%Y-%m-%d')
                df_copy['Time'] = df_copy.index.strftime('%H:%M:%S')
                df_copy = df_copy[['Ticker', 'Date', 'Time', 'Open', 'High', 'Low', 'Close', 'Volume']]
                all_data[ticker] = df_copy
            else:
                summary['failed'].append(ticker)
        
        summary_file = self.data_dir / f"summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2, default=str)
        
        if all_data:
            self.generate_unified_file(all_data, interval='5m')
        
        if os.getenv('GITHUB_ACTIONS'):
            print(f"\n::set-output name=success_count::{len(summary['success'])}")
            print(f"::set-output name=failed_count::{len(summary['failed'])}")
            print(f"\n### 📈 Resumo Coleta B3 (Horário BRT)")
            print(f"- ✅ Sucesso: {len(summary['success'])} ativos")
            print(f"- ❌ Falhas: {len(summary['failed'])} ativos")
            for s in summary['success']:
                print(f"- {s['ticker']}: {s['records']} registros ({s['time_range']})")
        
        return summary
    
    def run(self, interval='5m', tickers=None):
        """Executa coleta completa"""
        tickers = tickers or self.config['tickers']
        results = {}
        
        print(f"🚀 Iniciando coleta B3 - {datetime.now()}")
        print(f"🌎 Fuso horário: BRT (Brasília, UTC-3)")
        print(f"📋 Ativos: {', '.join(tickers)}")
        print(f"⏱️ Intervalo: {interval}")
        print(f"📝 Formato: Ticker,Date,Time,Open,High,Low,Close,Volume")
        print("=" * 60)
        
        for ticker in tickers:
            df = self.fetch_intraday(ticker, interval)
            if df is not None:
                self.export_amibroker_format(df, ticker, interval)
            results[ticker] = df
            time.sleep(2)
        
        print("\n" + "=" * 60)
        summary = self.generate_summary(results)
        
        failed = len(summary['failed'])
        if failed == len(tickers):
            print("🚨 Todos os ativos falharam!")
            return 1
        elif failed > 0:
            print(f"⚠️ {failed} ativos falharam, mas continuando...")
        
        print(f"\n✅ Coleta finalizada! Horários em BRT (10:00-17:00 pregão)")
        return 0


def main():
    import argparse
    parser = argparse.ArgumentParser(description='B3 Intraday Scraper para AmiBroker (BRT)')
    parser.add_argument('--interval', default='5m', help='Timeframe (1m, 5m, 15m, 1h)')
    parser.add_argument('--tickers', nargs='+', help='Lista de tickers específicos')
    parser.add_argument('--data-dir', default='data/intraday', help='Diretório de saída')
    args = parser.parse_args()
    
    scraper = B3GitHubScraper(data_dir=args.data_dir)
    exit_code = scraper.run(interval=args.interval, tickers=args.tickers)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
