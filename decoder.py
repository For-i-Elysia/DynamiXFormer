import torch
import torch.nn as nn
import torch.nn.functional as F
from tools import *

class DecoderLayer(nn.Module):
    def __init__(self, self_attention, cross_attention, d_model, c_out, d_ff=None,
                 series_decomp=0.1, dropout=0.1, activation="relu", use_apdc=True):
        super(DecoderLayer, self).__init__()
        d_ff = d_ff or 4 * d_model
        self.self_attention = self_attention
        self.cross_attention = cross_attention
        self.conv1 = nn.Conv1d(in_channels=d_model, out_channels=d_ff, kernel_size=1, bias=False)
        self.conv2 = nn.Conv1d(in_channels=d_ff, out_channels=d_model, kernel_size=1, bias=False)
        
        self.decomp1 = fourier_decomp(series_decomp)
        self.decomp2 = fourier_decomp(series_decomp)
        self.decomp3 = fourier_decomp(series_decomp)
        
        self.dropout = nn.Dropout(dropout)
        self.projection = nn.Conv1d(in_channels=d_model, out_channels=c_out, kernel_size=3, stride=1, padding=1,
                                    padding_mode='circular', bias=False)
        self.activation = F.relu if activation == "relu" else F.gelu
        self.use_apdc = use_apdc
        self.apdc = AdaptiveFreqDenoiseBlock(dim=d_model)

        self.norm1 = nn.LayerNorm(d_model)  
        self.norm2 = nn.LayerNorm(d_model)  
        self.norm3 = nn.LayerNorm(d_model)  

    def forward(self, x, cross, x_mask=None, cross_mask=None):
        x = self.norm1(x + self.dropout(self.self_attention(
            x, x, x, attn_mask=x_mask
        )[0]))

        x, trend1 = self.decomp1(x)

        x = self.norm2(x + self.dropout(self.cross_attention(
            x, cross, cross, attn_mask=cross_mask
        )[0]))

        x, trend2 = self.decomp2(x)

        y = x
        y = self.dropout(self.activation(self.conv1(y.transpose(-1, 1))))
        y = self.dropout(self.conv2(y).transpose(-1, 1))

        x, trend3 = self.decomp3(x + y)
        residual_trend = trend1 + trend2 + trend3
        residual_trend = self.projection(residual_trend.permute(0, 2, 1)).transpose(1, 2)
        
        if self.use_apdc:
            x = self.apdc(x)

        return self.norm3(x), residual_trend  

class Decoder(nn.Module):
    def __init__(self, layers, norm_layer=None, projection=None):
        super(Decoder, self).__init__()
        self.layers = nn.ModuleList(layers)
        self.norm = norm_layer
        self.projection = projection

    def forward(self, x, cross, x_mask=None, cross_mask=None, trend=None):
        for layer in self.layers:
            x, residual_trend = layer(x, cross, x_mask=x_mask, cross_mask=cross_mask)
            if trend is not None:
                trend = trend + residual_trend
            else: trend = residual_trend

        if self.norm is not None:
            x = self.norm(x)

        if self.projection is not None:
            x = self.projection(x)
        return x, trend
