%% Overall ESS File
% This function calculates the NPV of an ESS for frequency response using
% the capacity of 2 ESSs as inputs. 
clear all
clc


% NOTE: When decribing power it is relative to the ESS. This means the a
% -ve power is a ESS charging and a +ve power is it discharging





%% Nomenclature

%function [NPV] = System(Cap1 Cap2)

% Frequency data is loaded into workspace
load('Frequency.mat')

% Define size of output arrays
P_Required = zeros(1,length(Fr));
P_output1 = zeros(1,length(Fr));
P_output2 = zeros(1,length(Fr));
SOC1 = zeros(1,length(Fr)); SOC10 = zeros(1,length(Fr));
SOC2 = zeros(1,length(Fr)); SOC20 = zeros(1,length(Fr));
Cap = [10 0.1];
SOH = 1;
% A for loop is created for each second of frequency data
gamma_d = 1; SOC10(1) = 0.5; SOC20(1) = 0.5;
    % The required power is calculated from the Power Function
    P_Required = PowerFreq(Fr);

for i = 1:length(Fr)
    
  % The control function is implemented 
  [P_output1(i), P_output2(i),SOC1(i),SOC2(i),b] = Control(P_Required(i), SOC10(i), SOC20(i), Cap);
  SOC10(i+1) = SOC1(i); P_output1(i+1) = P_output1(i);
  SOC20(i+1) = SOC2(i); P_output2(i+1) = P_output2(i);
  P_Out(i) = (P_output1(i)*b(1) + P_output2(i)*b(2))'; 
  
  % The degradation is calculated each month
  if mod(i,2628000)==0 % This determines a month interval
      n = (i/2628000);
      [L_cyc, L_cal] = cycle_count(SOC1(1:i),[1:i]);
      L = L_cal + sum(L_cyc); 
      SOH = 1 - L;
  end
  if SOH < 0.8
      break
  end
  
end

%%
% The power not delivered is calculated
P_Missed = (abs(P_Required(1:i)) - abs(P_Out));
P_Missed = P_Missed';
% The missed power and required power are converted into a matrix where
% each column represents one month
P_Missed_Month = reshape(P_Missed,2628000,n);
P_Required_Month = reshape(P_Required(1:i),2628000,n);
% Set NPV function inputs.
NPV_In.P_Missed = sum(P_Missed_Month);
NPV_In.P_Required = sum(abs(P_Required_Month));
NPV_In.Cap1 = Cap(1);
NPV_In.Cap2 = Cap(2);

% Call NPV function
[NPV_Out] = NPV(NPV_In);

