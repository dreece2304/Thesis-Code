%% MulitCash

clf
clear all
clc
i = 1;
for P = 10000000:-500000:500000
    
    Cap = [5 0.05 1];
   
    CF = []; Month = [];
    [NPV1(i),SOC1avg(i), Lifetime(i), CF, Month] = System(Cap,P);
    hold on
    plot(Month, CF)
    i = i + 1;
end
%% 
