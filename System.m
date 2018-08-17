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
%P_Required = zeros(1,length(Fr));
%P_output1 = zeros(1,length(Fr));
%P_output2 = zeros(1,length(Fr));
%SOC1 = zeros(1,length(Fr));
%SOC2 = zeros(1,length(Fr));
Cap = [5 2.5];
% A for loop is created for each second of frequency data
gamma_d = 1; SOC10 = 0.5; SOC20 = 0.5;
    % The required power is calculated from the Power Function
    P_Required = PowerFreq(Fr(1:100000));
for i = 1:100000
    
  % The control function is implemented 
  [P_output1(i), P_output2(i),SOC1(i),SOC2(i)] = Control(P_Required(i), SOC10(i), SOC20(i), Cap);
  SOC10(i+1) = SOC1(i); P_output1(i+1) = P_output1(i);
  SOC20(i+1) = SOC2(i); P_output2(i+1) = P_output2(i);
  P_Out(i) = (P_output1(i) + P_output2(i))'; 
  
  % The degradation is calculated each month
  %if i == 2628000 || i == 2628000 
  
end
P_Required = P_Required';
P_Missed = (abs(P_Required) - abs(P_Out));
P_Missed = P_Missed';
P_Missed_Month = reshape(P_Misses,2628000,1);
P_Required_Month = reshape(P_Required,2628000,1);
% Set NPV function inputs.
NPV_In.P_Missed = P_Missed_Month;
NPV_In.P_Required = P_Required_Month;
NPV_In.Cap1 = Cap(1);
NPV_In.Cap2 = Cap(2);

% Call NPV function
[NPV_Out] = NPV(NPV_In);

