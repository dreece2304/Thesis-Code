function [NPV_Out] = NPV(NPV_In)
% This is the function to calculate the NPV of the designed ESS

%% Nomenclature
% INPUTS
%   NPV_In is a structured array input made up of the following:
%   P_Missed = Power requirement not met each month, vector
%   P_Required = Power Requirement each month, vector
%   Cap1 = Capacity of system 1, scalar
%   Cap2 = Capacity of system 2, scalar
% 
% OUTPUTS
%   NPV_Out is a structured array of outputs made up of the following:
%   NPV = Final NPV for designed system, scalar
%   CAPEX = Initial investment for total system, scalar
%   Cash = Cash flow each month, vector
%   Month = corresponding month for cash flow, vector
%
%% Define Constants
Rev = 8; % Revenue from NG each month in $/(MW.Month)
Cost_1 = 500000; % Specific cost of Battery system in $/MWh
Cost_2 = 1000000; % Specific cost of SC system in $/MWh
i = 0.08/12; % Internal rate of return per month

%% Function Code
Revenue = Rev*730*2*NPV_In.Cap1;
OPEX = (0.01*(NPV_In.Cap1))/12; % OPEX is ~1% of equipment cost for the year.
R0 = Cost_1*NPV_In.Cap1 + Cost_2*NPV_In.Cap2; % Initial investment is calculated
% A FOR loop is used to calculate the cash flow at the end of each month
Cash_Flow = zeros(1, length(NPV_In.P_Missed));
CF(1) = -R0;
for t = 1:length(NPV_In.P_Missed)
    R_t(t) = (1-(NPV_In.P_Missed(t)/NPV_In.P_Required(t)))*Revenue - OPEX; % Change once talked to Adrien and add in price of electricity when balancing.
    Cash_Flow(t) = R_t(t)/(1 + i)^t;
    month(t) = t; CF(t+1) = CF(t) + R_t(t)/(1 + i)^t;
end

% Now the total NPV can be calculated
NPV = -R0 + sum(Cash_Flow);

% Output values as structured array
NPV_Out.NPV = NPV;
NPV_Out.CAPEX = -R0;
NPV_Out.Cash = CF;
NPV_Out.Month = [0,month];
x = [1:i];

end


