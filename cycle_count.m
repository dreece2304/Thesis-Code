function [ L_cyc, L_cal] = cycle_count(SOC1,t)
% This function takes the SOC profile of the battery, converts it into
% cycles using a rainflow algorithm and calculates the estimated
% degradation for each cycle as well as the calander ageing. 

%% Nomenclature

%% Define Constants
kd1 = 2.0e5; % kdi are the parameters for the DoD stress factor
kd2 = -5.01e-1;
kd3 = -1.23e5;
kt = 4.14e-12; % Degradation with time parameter
ksig = 1.04; % Stress parameter for SOC


%% Rainflow Algorithm
% This section converts the SOC profile from time domain into equivalent
% cycles
[ext, exttime] = sig2ext(SOC1, t); % The turning points and corresponding times are found of the SOC profile

rf = rainflow(ext, exttime)'; % The rainflow algorithm function is used 
rf = sortrows(rf,4); % This sorts the matrix to be the order of the start time of each column in accending order

DoD = 2.*rf(:,1);% Depth of Discharge
SOC_cycle = rf(:,2);% SOC of each cycle
t_c = rf(:,5); % Time of each cycle
n_i = rf(:,3); % No. of cycle (0.5 or 1)
SOC_avg = mean(SOC_cycle); % Overall average of the SOC for time t
Start = rf(:,3);

L_cyc = zeros(1,length(DoD));

for i = 1:length(DoD)
L_cyc(i+1) =  n_i(i)*exp(ksig*(SOC_cycle(i)-0.5))*((kd1*DoD(i)^(kd2) + kd3)^-1); % cyclic degradation equation

end
L_cal = (kt*t(end))*exp(ksig*(SOC_avg-0.5)); % Calander degradation equation
L = L_cal + sum(L_cyc); % Total degradation 

end
