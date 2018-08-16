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
%P_output1 = zeros(1,length(Fr));
%P_output2 = zeros(1,length(Fr));
%SOC1 = zeros(1,length(Fr));
SOC2 = zeros(1,length(Fr));
Cap = [10 5];
% A for loop is created for each second of frequency data
gamma_d = 1; SOC10 = 0.5; SOC20 = 0.5;
for i = 1:100000
    
    % The required power is calculated from the Power Function
    P_Required(i) = PowerFreq(Fr(i));
    
    % The control function is implemented 
  [P_output1(i), P_output2(i),SOC1(i),SOC2(i)] = Control(P_Required(i), SOC10(i), SOC20(i), Cap);
  SOC10(i+1) = SOC1(i); P_output1(i+1) = P_output1(i);
  SOC20(i+1) = SOC2(i); P_output2(i+1) = P_output2(i);
end
