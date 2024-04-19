from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import pandas as pd
import requests
from matplotlib import dates
import streamlit as st
import plotly.graph_objects as go

# Set plot style
plt.style.use("seaborn-v0_8-dark")
for param in ["figure.facecolor", "axes.facecolor", "savefig.facecolor"]:
    plt.rcParams[param] = "#212946"
for param in ["text.color", "axes.labelcolor", "xtick.color", "ytick.color"]:
    plt.rcParams[param] = "0.9"
plt.rcParams["font.size"] = 6

contract_size = 100

# Set page configuration and style
st.set_page_config(
    page_title="Market Data Analysis App",
    page_icon=":chart_with_upwards_trend:",
    layout="wide",
)
st.markdown(
    """
<style>
.main {
   background-color: #212946;
}
</style>
""",
    unsafe_allow_html=True,
)

height = 800


def scrape_data(ticker):
    """Scrape data from CBOE website"""
    try:
        data = requests.get(
            f"https://cdn.cboe.com/api/global/delayed_quotes/options/_{ticker}.json"
        ).json()
    except ValueError:
        data = requests.get(
            f"https://cdn.cboe.com/api/global/delayed_quotes/options/{ticker}.json"
        ).json()
    # Convert json to pandas DataFrame
    data = pd.DataFrame.from_dict(data)

    spot_price = data.loc["current_price", "data"]
    option_data = pd.DataFrame(data.loc["options", "data"])

    return spot_price, fix_option_data(option_data)


def fix_option_data(data):
    """
    Fix option data columns.

    From the name of the option derive type of option, expiration and strike price
    """
    data["type"] = data.option.str.extract(r"\d([A-Z])\d")
    data["strike"] = data.option.str.extract(r"\d[A-Z](\d+)\d\d\d").astype(int)
    data["expiration"] = data.option.str.extract(r"[A-Z](\d+)").astype(str)
    # Convert expiration to datetime format
    data["expiration"] = pd.to_datetime(data["expiration"], format="%y%m%d")
    return data


def compute_total_gex(spot, data):
    """Compute dealers' total GEX"""
    # Compute gamma exposure for each option
    data["GEX"] = spot * data.gamma * data.open_interest * contract_size * spot * 0.01

    # For put option we assume negative gamma, i.e. dealers sell puts and buy calls
    data["GEX"] = data.apply(lambda x: -x.GEX if x.type == "P" else x.GEX, axis=1)
    print(f"Total notional GEX: ${round(data.GEX.sum() / 10 ** 9, 4)} Bn")


def compute_gex_by_strike(spot, data, ticker):
    """Compute and plot GEX by strike using Plotly for interactivity"""
    # Compute total GEX by strike
    gex_by_strike = data.groupby("strike")["GEX"].sum() / 10**9

    # Limit data to +- 15% from spot price
    limit_criteria = (gex_by_strike.index > spot * 0.85) & (
        gex_by_strike.index < spot * 1.15
    )
    limited_gex = gex_by_strike[limit_criteria]
    tick_step = max(1, len(limited_gex) // 20)  # at most 15 labels on the x-axis

    # Create a plot using Plotly
    fig = go.Figure(
        data=[
            go.Bar(
                x=limited_gex.index,
                y=limited_gex,
                text=limited_gex.round(2),
                textposition="auto",
                marker_color="#FE53BB",
            )
        ]
    )

    fig.update_layout(
        title=f"{ticker} GEX by Strike",
        xaxis_title="Strike",
        yaxis_title="Gamma Exposure (Bn$)",
        plot_bgcolor="#212946",
        paper_bgcolor="#212946",
        font=dict(color="#7FDBFF"),
        xaxis=dict(
            tickmode="linear",
            tick0=limited_gex.index.min(),
            dtick=tick_step,
            tickangle=-45,
        ),
        height=height,
    )

    st.plotly_chart(fig, use_container_width=True)


def compute_gex_by_expiration(data, ticker):
    """Compute and plot GEX by expiration using Plotly for interactivity"""
    # Limit data to one year
    selected_date = datetime.today() + timedelta(days=365)
    data = data[data["expiration"] < selected_date]
    gex_by_expiration = data.groupby("expiration")["GEX"].sum() / 10**9

    fig = go.Figure(
        data=[
            go.Bar(
                x=gex_by_expiration.index,
                y=gex_by_expiration.values,
                marker_color="#FE53BB",
            )
        ]
    )

    # Adjusting margins and the positioning of the range slider
    fig.update_layout(
        title=f"{ticker} GEX by Expiration",
        xaxis_title="Expiration Date",
        yaxis_title="Gamma Exposure (Bn$)",
        plot_bgcolor="#212946",
        paper_bgcolor="#212946",
        font=dict(color="#7FDBFF"),
        height=height + 200,  # Set the height of the plot
        hovermode="closest",  # Updates hover mode
        margin=dict(t=60, l=50, r=50, b=100),  # Top, Left, Right, Bottom margins
        xaxis=dict(
            tickangle=-45,
            tickformat="%b %d, %Y",
            tickmode="auto",
            nticks=20,  # Limits the number of ticks
            rangeslider=dict(
                visible=True,
                thickness=0.05,  # Adjusts the thickness of the range slider
            ),
            domain=[0.05, 0.95],  # Leaves space at the bottom for the range slider
        ),
    )

    st.plotly_chart(fig, use_container_width=True)


def print_gex_surface(spot, data, ticker):
    """Plot 3D surface of GEX using Plotly with reversed strikes and axes swapped"""
    # Limit data to 1 year and +- 15% from ATM
    selected_date = datetime.today() + timedelta(days=365)
    limit_criteria = (
        (data["expiration"] < selected_date)
        & (data["strike"] > spot * 0.85)
        & (data["strike"] < spot * 1.15)
    )
    limited_data = data[limit_criteria]

    # Compute GEX by expiration and strike
    grouped_data = limited_data.groupby(["expiration", "strike"])["GEX"].sum() / 10**6
    grouped_data = grouped_data.reset_index()

    # Format and sort dates
    grouped_data["expiration"] = grouped_data["expiration"].dt.strftime("%Y-%m-%d")
    grouped_data.sort_values("expiration", inplace=True)

    # Create grid values needed for 3D surface plot
    x_unique = sorted(
        grouped_data["expiration"].unique(), reverse=True
    )  # Sorted unique expiration dates
    y_unique = sorted(grouped_data["strike"].unique())  # Reversed sorted strikes
    z = (
        grouped_data.pivot(index="strike", columns="expiration", values="GEX")
        .fillna(0)
        .values
    )

    fig = go.Figure(
        data=[
            go.Surface(
                z=z,
                x=x_unique,
                y=y_unique,
                colorscale="Viridis",
                cmin=z.min(),
                cmax=z.max(),
            )
        ]
    )

    # Adjustments for the tick placement and formatting
    x_ticks = max(1, len(x_unique) // 10)  # Show at most 10 x-axis labels
    y_ticks = max(1, len(y_unique) // 10)  # Show at most 10 y-axis labels

    fig.update_layout(
        title=f"{ticker} Gamma Exposure Surface",
        scene=dict(
            xaxis_title="Expiration Date",
            yaxis_title="Strike Price",
            zaxis_title="Gamma (M$)",
            xaxis=dict(
                tickmode="array",
                tickvals=x_unique[::x_ticks],
                ticktext=[x for x in x_unique[::x_ticks]],
            ),
            yaxis=dict(
                tickmode="array",
                tickvals=y_unique[::y_ticks],
                ticktext=[f"{int(y)}" for y in y_unique[::y_ticks]],
            ),
            zaxis=dict(tickmode="linear"),
        ),
        autosize=False,
        width=height,
        height=height - 100,
        margin=dict(l=65, r=50, b=65, t=90),
    )

    st.plotly_chart(fig, use_container_width=True)


def main():
    st.title("Gamma Exposure by Strike and Expiration")
    ticker = st.text_input("Enter the Ticker Symbol", "SPY").upper()

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Run Analysis"):
            spot_price, option_data = scrape_data(ticker)
            if option_data is not None and spot_price is not None:
                compute_total_gex(spot_price, option_data)
                compute_gex_by_strike(spot_price, option_data, ticker)
                compute_gex_by_expiration(option_data, ticker)
                print_gex_surface(spot_price, option_data, ticker)
            else:
                st.error("Data retrieval was unsuccessful.")


if __name__ == "__main__":
    main()
