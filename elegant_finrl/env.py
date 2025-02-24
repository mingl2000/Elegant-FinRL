import os
import numpy as np
import numpy.random as rd
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt
from stockstats import StockDataFrame as Sdf  # for Sdf.retype
from pyfolio import timeseries
import pyfolio
from copy import deepcopy

class StockTradingEnv:
    def __init__(self, cwd='./envs/FinRL', gamma=0.99,
                 max_stock=1e2, initial_capital=1e6, buy_cost_pct=1e-3, sell_cost_pct=1e-3,
                 start_date='2009-01-01', end_date='2019-01-01', env_eval_date='2021-01-01',
                 ticker_list=None, tech_indicator_list=None, initial_stocks=None, reward_scaling=2 ** -14, if_eval=False):

        self.date_list, self.price_ary, self.tech_ary = self.load_data(cwd, if_eval, ticker_list, tech_indicator_list,
                                                       start_date, end_date, env_eval_date, )
        stock_dim = self.price_ary.shape[1]
    
        self.gamma = gamma
        self.max_stock = max_stock
        self.buy_cost_pct = buy_cost_pct
        self.sell_cost_pct = sell_cost_pct
        self.initial_capital = initial_capital
        self.initial_stocks = np.zeros(stock_dim, dtype=np.float32) if initial_stocks is None else initial_stocks

        # reset()
        self.day = None
        self.amount = None
        self.stocks = None
        self.total_asset = None
        self.initial_total_asset = None
        self.gamma_reward = 0.0

        # environment information
        self.env_name = 'StockTradingEnv-v2'
        self.state_dim = 1 + 2 * stock_dim + self.tech_ary.shape[1]
        self.action_dim = stock_dim
        self.max_step = len(self.price_ary) - 1
        self.if_discrete = False
        self.target_return = 3.5
        self.episode_return = 0.0
        self.reward_scaling = reward_scaling

    def reset(self):
        self.day = 0
        price = self.price_ary[self.day]

        self.stocks = self.initial_stocks + rd.randint(0, 64, size=self.initial_stocks.shape)
        self.amount = self.initial_capital * rd.uniform(0.95, 1.05) - (self.stocks * price).sum()

        self.total_asset = self.amount + (self.stocks * price).sum()
        self.initial_total_asset = self.total_asset
        self.gamma_reward = 0.0

        state = np.hstack((self.amount * 2 ** -13,
                           price,
                           self.stocks,
                           self.tech_ary[self.day],)).astype(np.float32) * 2 ** -5
        return state

    def step(self, actions):
        actions = (actions * self.max_stock).astype(int)

        self.day += 1
        price = self.price_ary[self.day]

        for index in np.where(actions < 0)[0]:  # sell_index:
            if price[index] > 0:  # Sell only if current asset is > 0
                sell_num_shares = min(self.stocks[index], -actions[index])
                self.stocks[index] -= sell_num_shares
                self.amount += price[index] * sell_num_shares * (1 - self.sell_cost_pct)

        for index in np.where(actions > 0)[0]:  # buy_index:
            if price[index] > 0:  # Buy only if the price is > 0 (no missing data in this particular date)
                buy_num_shares = min(self.amount // price[index], actions[index])
                self.stocks[index] += buy_num_shares
                self.amount -= price[index] * buy_num_shares * (1 + self.buy_cost_pct)

        state = np.hstack((self.amount * 2 ** -13,
                           price,
                           self.stocks,
                           self.tech_ary[self.day],)).astype(np.float32) * 2 ** -5

        total_asset = self.amount + (self.stocks * price).sum()
        reward = (total_asset - self.total_asset) * self.reward_scaling  # reward scaling
        self.total_asset = total_asset

        self.gamma_reward = self.gamma_reward * self.gamma + reward
        done = self.day == self.max_step
        if done:
            reward = self.gamma_reward
            self.episode_return = total_asset / self.initial_total_asset

        return state, reward, done, dict()

    def load_data(self, cwd='./envs/FinRL', if_eval=None,
                  ticker_list=None, tech_indicator_list=None,
                  start_date='2008-03-19', end_date='2016-01-01', env_eval_date='2021-01-01'):
        raw_data_path = f'{cwd}/StockTradingEnv_raw_data.df'
        processed_data_path = f'{cwd}/StockTradingEnv_processed_data.df'
        data_path_array = f'{cwd}/StockTradingEnv_arrays_float16.npz'
        trade_data_path = f'{cwd}/StockTradingEnv_trading_data.df'

        tech_indicator_list = [
            'macd', 'boll_ub', 'boll_lb', 'rsi_30', 'cci_30', 'dx_30', 'close_30_sma', 'close_60_sma'
        ] if tech_indicator_list is None else tech_indicator_list

        ticker_list = [
            'AAPL', 'ADBE', 'ADI', 'ADP', 'ADSK', 'ALGN', 'ALXN', 'AMAT', 'AMD', 'AMGN',
            'AMZN', 'ASML', 'ATVI', 'BIIB', 'BKNG', 'BMRN', 'CDNS', 'CERN', 'CHKP', 'CMCSA',
            'COST', 'CSCO', 'CSX', 'CTAS', 'CTSH', 'CTXS', 'DLTR', 'EA', 'EBAY', 'FAST',
            'FISV', 'GILD', 'HAS', 'HSIC', 'IDXX', 'ILMN', 'INCY', 'INTC', 'INTU', 'ISRG',
            'JBHT', 'KLAC', 'LRCX', 'MAR', 'MCHP', 'MDLZ', 'MNST', 'MSFT', 'MU', 'MXIM',
            'NLOK', 'NTAP', 'NTES', 'NVDA', 'ORLY', 'PAYX', 'PCAR', 'PEP', 'QCOM', 'REGN',
            'ROST', 'SBUX', 'SIRI', 'SNPS', 'SWKS', 'TTWO', 'TXN', 'VRSN', 'VRTX', 'WBA',
            'WDC', 'WLTW', 'XEL', 'XLNX'
        ] if ticker_list is None else ticker_list  # finrl.config.NAS_74_TICKER
        
        '''get: train_price_ary, train_tech_ary, eval_price_ary, eval_tech_ary'''
        if os.path.exists(data_path_array):
            load_dict = np.load(data_path_array)

            train_price_ary = load_dict['train_price_ary'].astype(np.float32)
            train_tech_ary = load_dict['train_tech_ary'].astype(np.float32)
            eval_price_ary = load_dict['eval_price_ary'].astype(np.float32)
            eval_tech_ary = load_dict['eval_tech_ary'].astype(np.float32)
        else:
            processed_df = self.processed_raw_data(raw_data_path, processed_data_path,
                                                   ticker_list, tech_indicator_list)

            def data_split(df, start, end):
                data = df[(df.date >= start) & (df.date < end)]
                data = data.sort_values(["date", "tic"], ignore_index=True)
                data.index = data.date.factorize()[0]
                return data

            train_df = data_split(processed_df, start_date, end_date)
            eval_df = data_split(processed_df, end_date, env_eval_date)

            train_price_ary, train_tech_ary = self.convert_df_to_ary(train_df, tech_indicator_list)
            eval_price_ary, eval_tech_ary = self.convert_df_to_ary(eval_df, tech_indicator_list)

            np.savez_compressed(data_path_array,
                                train_price_ary=train_price_ary.astype(np.float16),
                                train_tech_ary=train_tech_ary.astype(np.float16),
                                eval_price_ary=eval_price_ary.astype(np.float16),
                                eval_tech_ary=eval_tech_ary.astype(np.float16), )

        if if_eval is None:
            price_ary = np.concatenate((train_price_ary, eval_price_ary), axis=0)
            tech_ary = np.concatenate((train_tech_ary, eval_tech_ary), axis=0)
        elif if_eval:
            price_ary = eval_price_ary
            tech_ary = eval_tech_ary
        else:
            price_ary = train_price_ary
            tech_ary = train_tech_ary
            
        date = self.get_date(trade_data_path, end_date, env_eval_date, ticker_list)
        return date, price_ary, tech_ary

    def processed_raw_data(self, raw_data_path, processed_data_path,
                           ticker_list, tech_indicator_list):
        if os.path.exists(processed_data_path):
            processed_df = pd.read_pickle(processed_data_path)  # DataFrame of Pandas
            # print('| processed_df.columns.values:', processed_df.columns.values)
            print(f"| load data: {processed_data_path}")
        else:
            print("| FeatureEngineer: start processing data (2 minutes)")
            fe = FeatureEngineer(use_turbulence=True,
                                 user_defined_feature=False,
                                 use_technical_indicator=True,
                                 tech_indicator_list=tech_indicator_list, )
            raw_df = self.get_raw_data(raw_data_path, ticker_list)

            processed_df = fe.preprocess_data(raw_df)
            processed_df.to_pickle(processed_data_path)
            print("| FeatureEngineer: finish processing data")

        '''you can also load from csv'''
        # processed_data_path = f'{cwd}/dow_30_daily_2000_2021.csv'
        # if os.path.exists(processed_data_path):
        #     processed_df = pd.read_csv(processed_data_path)
        return processed_df
    
    @staticmethod
    def get_date(path, start, end, ticker_list):
        if os.path.exists(path):
            raw_df = pd.read_pickle(path)  # DataFrame of Pandas
            print(f"| load data: {path}")
        else:
            raw_df = YahooDownloader(start_date=start,
                                         end_date=end,
                                         ticker_list=ticker_list, ).fetch_data()
            raw_df.to_pickle(path)
        print("| YahooDownloader: finish processing date list")
        return raw_df.date.unique()

    @staticmethod
    def get_raw_data(raw_data_path, ticker_list):
        if os.path.exists(raw_data_path):
            raw_df = pd.read_pickle(raw_data_path)  # DataFrame of Pandas
            # print('| raw_df.columns.values:', raw_df.columns.values)
            print(f"| load data: {raw_data_path}")
        else:
            print("| YahooDownloader: start downloading data (1 minute)")
            raw_df = YahooDownloader(start_date="2000-01-01",
                                     end_date="2021-01-01",
                                     ticker_list=ticker_list, ).fetch_data()
            # print(raw_df.loc['2000-01-01'])
            j = 40000
            check_ticker_list = set(raw_df.loc.obj.tic[j:j + 200].tolist())
            print(len(check_ticker_list), check_ticker_list)
            raw_df.to_pickle(raw_data_path)
            print("| YahooDownloader: finish downloading data")
        return raw_df

    @staticmethod
    def convert_df_to_ary(df, tech_indicator_list):
        tech_ary = list()
        price_ary = list()
        for day in range(len(df.index.unique())):
            item = df.loc[day]

            tech_items = [item[tech].values.tolist() for tech in tech_indicator_list]
            tech_items_flatten = sum(tech_items, [])
            tech_ary.append(tech_items_flatten)
            price_ary.append(item.close)  # adjusted close price (adjcp)

        price_ary = np.array(price_ary)
        tech_ary = np.array(tech_ary)
        print(f'| price_ary.shape: {price_ary.shape}, tech_ary.shape: {tech_ary.shape}')
        return price_ary, tech_ary

    def trade_prediction(self, args, _torch) -> list:
        state_dim = self.state_dim
        action_dim = self.action_dim

        agent = args.agent
        net_dim = args.net_dim
        cwd = args.cwd

        agent.init(net_dim, state_dim, action_dim)
        agent.save_load_model(cwd=cwd, if_save=False)
        act = agent.act
        device = agent.device

        state = self.reset()
        episode_returns = [1.0]  # the cumulative_return / initial_account
        with _torch.no_grad():
            for i in range(self.max_step):
                s_tensor = _torch.as_tensor((state,), device=device)
                a_tensor = act(s_tensor)
                action = a_tensor.cpu().numpy()[0]  # not need detach(), because with torch.no_grad() outside
                state, reward, done, _ = self.step(action)

                total_asset = self.amount + (self.price_ary[self.day] * self.stocks).sum()
                episode_return = total_asset / self.initial_total_asset
                episode_returns.append(episode_return)
                if done:
                    break
        # print(len(episode_returns))
        # print(len(self.date_list))
        # print(self.date_list)
        df_account_value = pd.DataFrame({'date':self.date_list,'account_value':episode_returns})
        return df_account_value
    
    @staticmethod
    def get_daily_return(df, value_col_name="account_value"):
        df = deepcopy(df)
        df["daily_return"] = df[value_col_name].pct_change(1)
        df["date"] = pd.to_datetime(df["date"])
        df.set_index("date", inplace=True, drop=True)
        #df.index = df.index.tz_localize("UTC")
        #return pd.Series(df["single-stock-baseline"], index=df.index)
        return pd.Series(df["daily_return"], index=df.index)
    
    def backtest_plot(self, account_value, baseline_start, baseline_end, baseline_ticker="^DJI"):
        df = deepcopy(account_value)
        test_returns = self.get_daily_return(df, value_col_name="account_value")
        
        baseline_df = self.get_baseline(ticker=baseline_ticker, start=baseline_start, end=baseline_end)
        baseline_returns = self.get_daily_return(baseline_df, value_col_name="close")
        
        with pyfolio.plotting.plotting_context(font_scale=1.1):
            pyfolio.create_full_tear_sheet(returns=test_returns, benchmark_rets=baseline_returns, set_context=False)
     
    @staticmethod
    def get_baseline(ticker, start, end):
        dji = YahooDownloader(
        start_date=start, end_date=end, ticker_list=[ticker]).fetch_data()
        return dji

"""Copy from FinRL"""


class YahooDownloader:
    """Provides methods for retrieving daily stock data from
    Yahoo Finance API
    from finrl.marketdata.yahoodownloader import YahooDownloader
    Attributes
    ----------
        start_date : str
            start date of the data (modified from config.py)
        end_date : str
            end date of the data (modified from config.py)
        ticker_list : list
            a list of stock tickers (modified from config.py)
    Methods
    -------
    fetch_data()
        Fetches data from yahoo API
    """

    def __init__(self, start_date: str, end_date: str, ticker_list: list):

        self.start_date = start_date
        self.end_date = end_date
        self.ticker_list = ticker_list

    def fetch_data(self) -> pd.DataFrame:
        """Fetches data from Yahoo API
        Parameters
        ----------
        Returns
        -------
        `pd.DataFrame`
            7 columns: A date, open, high, low, close, volume and tick symbol
            for the specified stock ticker
        """
        # Download and save the data in a pandas DataFrame:
        data_df = pd.DataFrame()
        for tic in self.ticker_list:
            temp_df = yf.download(tic, start=self.start_date, end=self.end_date)
            temp_df["tic"] = tic
            data_df = data_df.append(temp_df)
        # reset the index, we want to use numbers as index instead of dates
        data_df = data_df.reset_index()
        try:
            # convert the column names to standardized names
            data_df.columns = [
                "date",
                "open",
                "high",
                "low",
                "close",
                "adjcp",
                "volume",
                "tic",
            ]
            # use adjusted close price instead of close price
            data_df["close"] = data_df["adjcp"]
            # drop the adjusted close price column
            data_df = data_df.drop("adjcp", 1)
        except NotImplementedError:
            print("the features are not supported currently")
        # create day of the week column (monday = 0)
        data_df["day"] = data_df["date"].dt.dayofweek
        # convert date to standard string format, easy to filter
        data_df["date"] = data_df.date.apply(lambda x: x.strftime("%Y-%m-%d"))
        # drop missing data
        data_df = data_df.dropna()
        data_df = data_df.reset_index(drop=True)
        print("Shape of DataFrame: ", data_df.shape)
        # print("Display DataFrame: ", data_df.head())

        data_df = data_df.sort_values(by=['date', 'tic']).reset_index(drop=True)

        return data_df


class FeatureEngineer:
    """Provides methods for preprocessing the stock price data
    from finrl.preprocessing.preprocessors import FeatureEngineer
    Attributes
    ----------
        use_technical_indicator : boolean
            we technical indicator or not
        tech_indicator_list : list
            a list of technical indicator names (modified from config.py)
        use_turbulence : boolean
            use turbulence index or not
        user_defined_feature:boolean
            user user defined features or not
    Methods
    -------
    preprocess_data()
        main method to do the feature engineering
    """

    def __init__(
            self,
            use_technical_indicator=True,
            tech_indicator_list=None,  # config.TECHNICAL_INDICATORS_LIST,
            use_turbulence=False,
            user_defined_feature=False,
    ):
        self.use_technical_indicator = use_technical_indicator
        self.tech_indicator_list = tech_indicator_list
        self.use_turbulence = use_turbulence
        self.user_defined_feature = user_defined_feature

    def preprocess_data(self, df):
        """main method to do the feature engineering
        @:param config: source dataframe
        @:return: a DataMatrices object
        """

        if self.use_technical_indicator:
            # add technical indicators using stockstats
            df = self.add_technical_indicator(df)
            print("Successfully added technical indicators")

        # add turbulence index for multiple stock
        if self.use_turbulence:
            df = self.add_turbulence(df)
            print("Successfully added turbulence index")

        # add user defined feature
        if self.user_defined_feature:
            df = self.add_user_defined_feature(df)
            print("Successfully added user defined features")

        # fill the missing values at the beginning and the end
        df = df.fillna(method="bfill").fillna(method="ffill")
        return df

    def add_technical_indicator(self, data):
        """
        calculate technical indicators
        use stockstats package to add technical inidactors
        :param data: (df) pandas dataframe
        :return: (df) pandas dataframe
        """

        df = data.copy()
        df = df.sort_values(by=['tic', 'date'])
        stock = Sdf.retype(df.copy())
        unique_ticker = stock.tic.unique()

        for indicator in self.tech_indicator_list:
            indicator_df = pd.DataFrame()
            for i in range(len(unique_ticker)):
                try:
                    temp_indicator = stock[stock.tic == unique_ticker[i]][indicator]
                    temp_indicator = pd.DataFrame(temp_indicator)
                    temp_indicator['tic'] = unique_ticker[i]
                    temp_indicator['date'] = df[df.tic == unique_ticker[i]]['date'].to_list()
                    indicator_df = indicator_df.append(
                        temp_indicator, ignore_index=True
                    )
                except Exception as e:
                    print(e)
            df = df.merge(indicator_df[['tic', 'date', indicator]], on=['tic', 'date'], how='left')
        df = df.sort_values(by=['date', 'tic'])
        return df

    def add_turbulence(self, data):
        """
        add turbulence index from a precalcualted dataframe
        :param data: (df) pandas dataframe
        :return: (df) pandas dataframe
        """
        df = data.copy()
        turbulence_index = self.calculate_turbulence(df)
        df = df.merge(turbulence_index, on="date")
        df = df.sort_values(["date", "tic"]).reset_index(drop=True)
        return df

    @staticmethod
    def add_user_defined_feature(data):
        """
         add user defined features
        :param data: (df) pandas dataframe
        :return: (df) pandas dataframe
        """
        df = data.copy()
        df["daily_return"] = df.close.pct_change(1)
        # df['return_lag_1']=df.close.pct_change(2)
        # df['return_lag_2']=df.close.pct_change(3)
        # df['return_lag_3']=df.close.pct_change(4)
        # df['return_lag_4']=df.close.pct_change(5)
        return df

    @staticmethod
    def calculate_turbulence(data):
        """calculate turbulence index based on dow 30"""
        # can add other market assets
        df = data.copy()
        df_price_pivot = df.pivot(index="date", columns="tic", values="close")
        # use returns to calculate turbulence
        df_price_pivot = df_price_pivot.pct_change()

        unique_date = df.date.unique()
        # start after a year
        start = 252
        turbulence_index = [0] * start
        # turbulence_index = [0]
        count = 0
        for i in range(start, len(unique_date)):
            current_price = df_price_pivot[df_price_pivot.index == unique_date[i]]
            # use one year rolling window to calcualte covariance
            hist_price = df_price_pivot[
                (df_price_pivot.index < unique_date[i])
                & (df_price_pivot.index >= unique_date[i - 252])
                ]
            # Drop tickers which has number missing values more than the "oldest" ticker
            filtered_hist_price = hist_price.iloc[hist_price.isna().sum().min():].dropna(axis=1)

            cov_temp = filtered_hist_price.cov()
            current_temp = current_price[[x for x in filtered_hist_price]] - np.mean(filtered_hist_price, axis=0)
            temp = current_temp.values.dot(np.linalg.pinv(cov_temp)).dot(
                current_temp.values.T
            )
            if temp > 0:
                count += 1
                if count > 2:
                    turbulence_temp = temp[0][0]
                else:
                    # avoid large outlier because of the calculation just begins
                    turbulence_temp = 0
            else:
                turbulence_temp = 0
            turbulence_index.append(turbulence_temp)

        turbulence_index = pd.DataFrame(
            {"date": df_price_pivot.index, "turbulence": turbulence_index}
        )
        return turbulence_index
